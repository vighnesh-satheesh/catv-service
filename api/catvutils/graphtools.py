MULTIPLIER = 0.4
EDGE_WIDTH_MAX = 4
EDGE_WIDTH_MIN = 1
DIST_DEPTH_OFFSET = 0
SOURCE_DEPTH_OFFSET = 1


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


class NodesCollection:
    def __init__(self):
        self.__nodes = {}
        self.__node_enum = {}

    def get_nodes(self):
        return self.__nodes

    def get_nodes_as_dict(self):
        return {k: v.__dict__ for k, v in self.__nodes.items()}

    def get_node(self, address):
        return self.get_nodes()[address]

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
        annotation=result[0][inner + '_annotation'],
        type=result[0][inner + '_type'],
        depth=0
    )

    nc.add_node(temp_node)

    exclusions = {result[0][inner]: result[0]}
    for item in uniqfy_generator(result, outer, exclusions):
        item_depth = (item['depth'] + depth_offset) * mode
        temp_node = Node(
            id=mode*counter,
            address=item[outer],
            annotation=item[outer + '_annotation'],
            type=item[outer + '_type'],
            depth=item_depth,
            balance=item[outer + '_balance'],
            amount_in=item[outer + '_amount_in'],
            amount_out=item[outer + '_amount_out'],
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
        item_dict.update((k, (v + SOURCE_DEPTH_OFFSET) * (-1)) for k, v in item_dict.items() if k == "depth")


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
