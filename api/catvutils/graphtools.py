MULTIPLIER = 0.4
EDGE_WIDTH_MAX = 4
EDGE_WIDTH_MIN = 1
DIST_DEPTH_OFFSET = 0
SOURCE_DEPTH_OFFSET = 1
BTC_DIST_DEPTH_OFFSET = 1
BTC_SOURCE_DEPTH_OFFSET = 1


class Node:
    def __init__(self, id, address, annotation, type, depth, balance=None,
                 amount_in=None, amount_out=None, trdb_info=None):
        self.id = id
        self.address = address
        self.annotation = annotation
        self.type = type
        self.level = depth
        self.label = address[:8]
        self.balance = balance
        self.amount_in = amount_in
        self.amount_out = amount_out
        self.trdb_info = trdb_info
        self.group = ""
        self.set_group_from_annotation()

    def set_group_from_annotation(self):
        annotation_list = self.annotation.split(", ")
        if 'Scamming' in annotation_list or 'Phishing' in annotation_list:
            self.group = 'Suspicious'
        # exchange could appear as "Exchange Wallet" for example
        elif 'Dex' in annotation_list or 'Exchange' in self.annotation:
            self.group = 'Exchange & DEX'
        elif self.type != 'Wallet':
            self.group = 'Smart Contract'
        elif self.annotation:
            self.group = 'Annotated'
        else:
            self.group = "No Tag"

    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class BTCNode(Node):
    def __init__(self, **kwargs):
        super(BTCNode, self).__init__(**kwargs)

    def set_group_from_annotation(self):
        annotation_list = self.annotation.split(", ")
        if 'Scamming' in annotation_list or 'Phishing' in annotation_list:
            self.group = 'Suspicious'
        # exchange could appear as "Exchange Wallet" for example
        elif 'Dex' in annotation_list or 'Exchange' in self.annotation:
            self.group = 'Exchange & DEX'
        elif self.annotation:
            self.group = 'Annotated'
        else:
            self.group = "No Tag"


class NodesCollection:
    def __init__(self):
        self.__nodes = {}
        self.__node_enum = {}

    def get_nodes(self):
        return self.__nodes

    def get_nodes_as_dict(self):
        return {k: v.__dict__ for k, v in self.__nodes.items()}

    def get_node(self, address):
        return self.get_nodes().get(address, None)

    def add_node(self, Node):
        self.__nodes[Node.address] = Node

    def get_node_enum(self):
        return {k: v.id for k, v in self.__nodes.items()}

    def update_node(self, node_key, node_value):
        self.__nodes[node_key] = node_value


def uniqfy_generator(seq, addr_key, exclusions):
    temp_dict = exclusions
    for e in seq:
        try:
            temp_dict[e[addr_key]]
        except KeyError:
            temp_dict[e[addr_key]] = e
            yield e


def create_edge(id, tx, node_enum):
    edge = {
        'id': id,
        'arrows': 'to',
        'sum': tx['amount'],
        'from': node_enum[tx['sender']],
        'to': node_enum[tx['receiver']],
        'data': [{
            'amount': tx['amount'],
            'tx_hash': tx['tx_hash'],
            'depth': tx['depth'],
            'tx_time': '{} {}'.format(tx['tx_time'].split("T")[0], tx['tx_time'].split("T")[1][:5])
        }]
    }
    return edge


def create_edge_btc(id, tx, node_enum):
    edge = {
        'id': id,
        'arrows': 'to',
        'sum': tx['sender_amount'],
        'from': node_enum[tx['sender']],
        'to': node_enum[tx['receiver']],
        'data': [{
            "ref_tx_id": tx["ref_tx_id"],
            "block_num": tx["block_num"],
            "vin_number": tx["vin_number"],
            'amount': tx['sender_amount'],
            'tx_hash': tx['ref_tx_id'],
            'depth': tx['depth'],
            'tx_time': tx['tx_time'],
            'tx_fees': tx['sender_amount'] - tx['receiver_amount']
        }]
    }
    return edge


def assign_edges(result, mode, node_enum):
    edge_dict = {}
    counter = 0
    for item in result:
        try:
            edge_dict[(item['sender'], item['receiver'])]['data'].append({
                'amount': item['amount'],
                'tx_hash': item['tx_hash'],
                'depth': item['depth'],
                'tx_time': '{} {}'.format(item['tx_time'].split("T")[0], item['tx_time'].split("T")[1][:5])
            })
            edge_dict[(item['sender'], item['receiver'])]['sum'] += item['amount']
        except KeyError:
            edge_dict[(item['sender'], item['receiver'])] = create_edge('{}_{}'.format(counter, mode), item, node_enum)
            counter += 1
        width = edge_dict[(item['sender'], item['receiver'])]["sum"] * MULTIPLIER
        if width > EDGE_WIDTH_MAX:
            edge_dict[(item['sender'], item['receiver'])]['width'] = EDGE_WIDTH_MAX
        elif width < EDGE_WIDTH_MIN:
            edge_dict[(item['sender'], item['receiver'])]['width'] = EDGE_WIDTH_MIN
        else:
            edge_dict[(item['sender'], item['receiver'])]['width'] = width
    return edge_dict


def assign_edges_btc(result, mode, node_enum):
    edge_dict = {}
    counter = 0
    for item in result:
        try:
            edge_dict[(item['sender'], item['receiver'])]['data'].append({
                "ref_tx_id": item["ref_tx_id"],
                "block_num": item["block_num"],
                "vin_number": item["vin_number"],
                'amount': item['sender_amount'],
                'tx_hash': item['ref_tx_id'],
                'depth': item['depth'],
                'tx_time': item['tx_time'],
                'tx_fees': item['sender_amount'] - item['receiver_amount']
            })
            edge_dict[(item['sender'], item['receiver'])]['sum'] += item['sender_amount']
        except KeyError:
            try:
                edge_dict[(item['sender'], item['receiver'])] = create_edge_btc('{}_{}'.format(counter, mode), item,
                                                                                node_enum)
                counter += 1
            except KeyError:
                pass
        try:
            width = edge_dict[(item['sender'], item['receiver'])]["sum"] * MULTIPLIER
            if width > EDGE_WIDTH_MAX:
                edge_dict[(item['sender'], item['receiver'])]['width'] = EDGE_WIDTH_MAX
            elif width < EDGE_WIDTH_MIN:
                edge_dict[(item['sender'], item['receiver'])]['width'] = EDGE_WIDTH_MIN
            else:
                edge_dict[(item['sender'], item['receiver'])]['width'] = width
        except KeyError:
            pass
    return edge_dict


def assign_nodes(result, mode):
    # mode = 1: distribution
    # mode = -1: source
    nc = NodesCollection()
    volume_count = {}
    counter = 1

    if mode == 1:
        outer = 'receiver'
        inner = 'sender'
        depth_offset = DIST_DEPTH_OFFSET
    elif mode == -1:
        outer = 'sender'
        inner = 'receiver'
        depth_offset = SOURCE_DEPTH_OFFSET

    temp_node = Node(
        id=0,
        address=result[0][inner],
        annotation=result[0].get(inner + '_annotation', ''),
        type=result[0].get(inner + '_type', 'Wallet'),
        depth=0
    )

    nc.add_node(temp_node)

    exclusions = {result[0][inner]: result[0]}
    for item in uniqfy_generator(result, outer, exclusions):
        item_depth = (item['depth'] + depth_offset) * mode
        temp_node = Node(
            id=mode*counter,
            address=item[outer],
            annotation=item.get(outer + '_annotation', ''),
            type=item.get(outer + '_type', 'Wallet'),
            depth=item_depth,
            balance=item.get(outer + '_balance', 0),
            amount_in=item.get(outer + '_amount_in', 0),
            amount_out=item.get(outer + '_amount_out', 0),
        )
        nc.add_node(temp_node)
        try:
            volume_count[item[inner]] += 1
        except KeyError:
            volume_count[item[inner]] = 1
        counter += 1
    return nc, volume_count


def assign_nodes_btc(result, mode, wallet_address):
    # mode = 1: distribution
    # mode = -1: source
    nc = NodesCollection()
    volume_count = {}
    counter = 1

    if mode == 1:
        outer = 'receiver'
        inner = 'sender'
        depth_offset = BTC_DIST_DEPTH_OFFSET
    elif mode == -1:
        outer = 'sender'
        inner = 'receiver'
        depth_offset = BTC_SOURCE_DEPTH_OFFSET

    root_node = list(filter(lambda x: x[inner].lower() == wallet_address.lower(), result))
    root_node = root_node[0]

    temp_node = BTCNode(
        id=0,
        address=root_node[inner],
        depth=0,
        annotation=root_node.get(inner + '_annotation', ""),
        type=root_node.get(inner + '_type', 'Wallet')
    )

    nc.add_node(temp_node)

    exclusions = {root_node[inner]: root_node}
    for item in uniqfy_generator(result, outer, exclusions):
        item_depth = (int(item['depth']) + depth_offset) * mode
        temp_node = BTCNode(
            id=mode * counter,
            address=item[outer],
            depth=item_depth,
            annotation=item.get(outer + '_annotation', ""),
            type=item.get(outer + '_type', 'Wallet'),
            balance=item.get(outer + '_balance', None),
            amount_in=item.get(outer + '_amount_in', None),
            amount_out=item.get(outer + '_amount_out', None)
        )
        nc.add_node(temp_node)
        try:
            volume_count[item[inner]] += 1
        except KeyError:
            volume_count[item[inner]] = 1
        counter += 1
    return nc, volume_count


def assign_nodes_btc_coinpath(result, mode):
    nc = NodesCollection()
    volume_count = {}
    counter = 1

    if mode == 1:
        outer = 'receiver'
        inner = 'sender'
    elif mode == -1:
        outer = 'sender'
        inner = 'receiver'

    temp_node = BTCNode(
        id=0,
        address=result[0][inner],
        annotation=result[0][inner + '_annotation'],
        type=result[0][inner + '_type'],
        depth=0,
        balance=0
    )

    nc.add_node(temp_node)

    exclusions = {result[0][inner]: result[0]}
    for item in uniqfy_generator(result, outer, exclusions):
        item_depth = (item['depth']) * mode
        temp_node = BTCNode(
            id=mode*counter,
            address=item[outer],
            annotation=item[outer + '_annotation'],
            type=item[outer + '_type'],
            depth=item_depth,
            balance=item.get(outer + '_balance', 0),
            amount_in=item['tx_value_in'],
            amount_out=item['tx_value_out']
        )
        nc.add_node(temp_node)
        try:
            volume_count[item[inner]] += 1
        except KeyError:
            volume_count[item[inner]] = 1
        counter += 1
    return nc, volume_count


def assign_nodes_btc_path(result, mode):
    # mode = 1: distribution
    # mode = -1: source
    nc = NodesCollection()
    volume_count = {}
    counter = 1

    if mode == 1:
        outer = 'receiver'
        inner = 'sender'
        depth_offset = DIST_DEPTH_OFFSET
    elif mode == -1:
        outer = 'sender'
        inner = 'receiver'
        depth_offset = SOURCE_DEPTH_OFFSET

    temp_node = Node(
        id=0,
        address=result[0][inner],
        annotation=result[0].get(inner + '_annotation', ''),
        type=result[0].get(inner + '_type', 'Wallet'),
        depth=0
    )

    nc.add_node(temp_node)

    exclusions = {result[0][inner]: result[0]}
    for item in uniqfy_generator(result, outer, exclusions):
        item_depth = (item['depth'] + depth_offset) * mode
        temp_node = Node(
            id=mode*counter,
            address=item[outer],
            annotation=item.get(outer + '_annotation', ''),
            type=item.get(outer + '_type', 'Wallet'),
            depth=item_depth,
            balance=item.get(outer + '_balance', 0),
            amount_in=item.get('tx_value_in', 0),
            amount_out=item.get('tx_value_out', 0),
        )
        nc.add_node(temp_node)
        try:
            volume_count[item[inner]] += 1
        except KeyError:
            volume_count[item[inner]] = 1
        counter += 1
    return nc, volume_count


def depth_shift_for_source(result):
    for item_dict in result:
        item_dict.update((k, (int(v) + SOURCE_DEPTH_OFFSET) * (-1)) for k, v in item_dict.items() if k == "depth")


def depth_shift_btc(result, mode):
    for item_dict in result:
        item_dict.update((k, (int(v)) * mode) for k, v in item_dict.items() if k == "depth")


def add_keys_btc(result):
    for item_dict in result:
        item_dict["tx_hash"] = item_dict["ref_tx_id"]


def generate_nodes_edges(result, mode):
    keys = list(result[0].keys())
    nc, volume_count = assign_nodes(result, mode)
    edge_dict = assign_edges(result, mode, nc.get_node_enum())
    if mode == -1:
        depth_shift_for_source(result)

    track_result = {'item_list': result, 'node_list': list(nc.get_nodes_as_dict().values()), 'keys': keys,
                    'node_enum': nc.get_node_enum(), 'edge_list': list(edge_dict.values()),
                    'volume_count_{}'.format(mode): volume_count}
    return track_result, nc


def generate_nodes_edges_btc(result, mode, wallet_address):
    keys = list(result[0].keys())
    nc, volume_count = assign_nodes_btc(result, mode, wallet_address)
    edge_dict = assign_edges_btc(result, mode, nc.get_node_enum())
    depth_shift_btc(result, mode)
    # add_keys_btc(result)

    track_result = {'item_list': result, 'node_list': list(nc.get_nodes_as_dict().values()), 'keys': keys,
                    'node_enum': nc.get_node_enum(), 'edge_list': list(edge_dict.values()),
                    'volume_count_{}'.format(mode): volume_count}
    return track_result, nc


def generate_nodes_edges_coinpath(result, mode):
    keys = list(result[0].keys())
    nc, volume_count = assign_nodes_btc_coinpath(result, mode)
    edge_dict = assign_edges(result, mode, nc.get_node_enum())
    if mode == -1:
        depth_shift_btc(result, mode)

    track_result = {'item_list': result, 'node_list': list(nc.get_nodes_as_dict().values()), 'keys': keys,
                    'node_enum': nc.get_node_enum(), 'edge_list': list(edge_dict.values()),
                    'volume_count_{}'.format(mode): volume_count}
    return track_result, nc


def generate_nodes_edges_ethcoinpath(result, mode):
    nodes = result[0]['path']
    keys = list(nodes[0].keys())
    item_list = []
    seen_tx_hash = []

    for path_info in result:
        for path in path_info['path']:
            if path['tx_hash'] not in seen_tx_hash:
                item_list.append(path)
                seen_tx_hash.append(path['tx_hash'])

    nc, volume_count = assign_nodes(item_list, mode)
    edge_dict = assign_edges(item_list, mode, nc.get_node_enum())

    if mode == -1:
        depth_shift_for_source(result)

    track_result = {'item_list': item_list, 'node_list': list(nc.get_nodes_as_dict().values()), 'keys': keys,
                    'node_enum': nc.get_node_enum(), 'edge_list': list(edge_dict.values()),
                    'volume_count_{}'.format(mode): volume_count}
    return track_result, nc


def generate_nodes_edges_btccoinpath(result, mode):
    nodes = result[0]['path']
    keys = list(nodes[0].keys())
    item_list = []
    seen_tx_hash = []

    for path_info in result:
        for path in path_info['path']:
            if path['tx_hash'] not in seen_tx_hash:
                item_list.append(path)
                seen_tx_hash.append(path['tx_hash'])

    nc, volume_count = assign_nodes_btc_path(item_list, mode)
    edge_dict = assign_edges(item_list, mode, nc.get_node_enum())

    if mode == -1:
        depth_shift_for_source(result)

    track_result = {'item_list': item_list, 'node_list': list(nc.get_nodes_as_dict().values()), 'keys': keys,
                    'node_enum': nc.get_node_enum(), 'edge_list': list(edge_dict.values()),
                    'volume_count_{}'.format(mode): volume_count}
    return track_result, nc
