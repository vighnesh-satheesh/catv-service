from multiprocessing.pool import ThreadPool
from multiprocessing import Pool
from datetime import datetime

from django.utils.timezone import make_aware
from django.conf import settings
from django.db.models import Q
from django.db.models.functions import Lower

from .bloxy_interface import BloxyAPIInterface
from .graphtools import (
    generate_nodes_edges, generate_nodes_edges_btc,
    generate_nodes_edges_coinpath, generate_nodes_edges_ethcoinpath,
    generate_nodes_edges_btccoinpath
)
from ..models import BloxyDistribution, BloxySource, Indicator, CaseStatus
from .vendor_api import LyzeAPIInterface, BloxyBTCAPIInterface, BloxyEthAPIInterface


def chunks(iterable, size):
    for i in range(0, len(iterable), size):
        yield iterable[i:i+size]


def find_key(_dict, key):
    return _dict[key] if key in _dict else None


class TrackingResults:
    def __init__(self, **kwargs):
        self._async_source_result = None
        self._async_dist_result = None
        self._async_source_graph = None
        self._async_dist_graph = None
        self._source_graph = None
        self._dist_graph = None
        self._skip_source = True
        self._skip_dist = True

        self.wallet_address = find_key(kwargs, 'wallet_address')
        self.source_depth = find_key(kwargs, 'source_depth')
        self.distribution_depth = find_key(kwargs, 'distribution_depth')
        self.transaction_limit = find_key(kwargs, 'transaction_limit')
        self.from_date = find_key(kwargs, 'from_date')
        self.to_date = find_key(kwargs, 'to_date')
        self.token_address = find_key(kwargs, 'token_address')
        self.force_lookup = find_key(kwargs, 'force_lookup')
        self.error = None
        self.ext_api_calls = 0
        self.error_messages = {"source": "", "distribution": ""}

    def bloxy_response_callback(self, *args, **kwargs):
        if args and 'error' in args[0]:
            self.error = args[0]['error']

    def get_results_from_bloxy(self, bloxy_interface, depth, till_date, tx_limit, limit, for_source=False):
        bloxy_response = bloxy_interface.get_transactions(self.wallet_address, tx_limit, limit, depth,
                                                          self.from_date, till_date, self.token_address, for_source)
        if not bloxy_response:
            error_key = "source" if for_source else "distribution"
            self.error_messages[error_key] = "Missing {} results for the wallet address within the date range " \
                                             "specified".format(error_key)
        return bloxy_response

    def save_bloxy_result(self, bloxy_db_class, depth, from_date, to_date, result):
        bloxy_db_class(address=self.wallet_address, depth_limit=depth, transaction_limit=self.transaction_limit,
                       from_time=from_date, till_time=to_date, result=result,
                       token_address=self.token_address, updated=make_aware(datetime.now())).save()

    def fetch_results(self, tx_limit, limit, save_to_db, for_source=False):
        till_date_extend = self.to_date + "T23:59:59"
        bloxy = BloxyAPIInterface(settings.BLOXY_API_KEY)

        if for_source:
            bloxy_db_class = BloxySource
            depth_limit = self.source_depth
            error_placeholder = "source"
        else:
            bloxy_db_class = BloxyDistribution
            depth_limit = self.distribution_depth
            error_placeholder = "distribution"

        aware_from_date = make_aware(datetime.strptime(self.from_date, '%Y-%m-%d'))
        aware_to_date = make_aware(datetime.strptime(self.to_date, '%Y-%m-%d'))
        try:
            if self.force_lookup:
                transaction_data = self.get_results_from_bloxy(bloxy, depth_limit, till_date_extend, tx_limit, limit, for_source)
                if save_to_db and transaction_data:
                    self.save_bloxy_result(bloxy_db_class, depth_limit, aware_from_date, aware_to_date, transaction_data)
                self.ext_api_calls += 1
            else:
                db_results = bloxy_db_class.objects.filter(address=self.wallet_address, depth_limit=depth_limit,
                                                           transaction_limit=self.transaction_limit,
                                                           token_address=self.token_address,
                                                           from_time__gte=aware_from_date,
                                                           till_time__lte=aware_to_date).values('result')\
                                                            .order_by('-id', '-updated', '-till_time',
                                                                      'from_time')[0:1]
                if not db_results or len(db_results[0]['result']) == 0:
                    transaction_data = self.get_results_from_bloxy(bloxy, depth_limit, till_date_extend, tx_limit, limit, for_source)
                    if save_to_db and transaction_data:
                        self.save_bloxy_result(bloxy_db_class, depth_limit, aware_from_date, aware_to_date,
                                               transaction_data)
                    self.ext_api_calls += 1
                else:
                    transaction_data = db_results[0]['result']
            return transaction_data
        except IndexError:
            self.error_messages[error_placeholder] = "Missing {} results for the wallet address within the date " \
                                                     "range specified".format(error_placeholder)

    def get_tracking_data(self, tx_limit, limit, save_to_db):
        pool = ThreadPool(processes=2)
        if self.source_depth:
            self._skip_source = False
            self._async_source_result = pool.apply_async(self.fetch_results, (tx_limit, limit, save_to_db, True),
                                                         callback=self.bloxy_response_callback)
        if self.distribution_depth:
            self._skip_dist = False
            self._async_dist_result = pool.apply_async(self.fetch_results, (tx_limit, limit, save_to_db, False),
                                                       callback=self.bloxy_response_callback)
        pool.close()
        pool.join()

    def create_graph_data(self):
        pool = Pool(processes=2)
        if not self._skip_source:
            source_result = self._async_source_result.get()
            if source_result:
                self._async_source_graph = pool.apply_async(generate_nodes_edges, (source_result, -1,))

        if not self._skip_dist:
            dist_result = self._async_dist_result.get()
            if dist_result:
                self._async_dist_graph = pool.apply_async(generate_nodes_edges, (dist_result, 1,))
        pool.close()
        pool.join()

    @staticmethod
    def update_annotations(nc, item_list, token_type):
        addr_list = nc.get_node_enum().keys()
        addr_list = [addr.lower() for addr in addr_list]
        indicators = []
        for chunk_addr in chunks(addr_list, 2000):
            query_list = Q(cases__status__in=[CaseStatus.RELEASED], pattern_subtype=token_type, pattern_type="cryptoaddr")
            query_list &= Q(pattern_lower__in=chunk_addr)
            matched_indicators = Indicator.objects.annotate(pattern_lower=Lower('pattern')).filter(query_list).\
                prefetch_related('cases').values('id', 'uid', 'security_category', 'security_tags', 'pattern', 'detail',
                                                'pattern_subtype', 'pattern_type', 'annotation').\
                order_by('-cases__updated')
            indicators.extend(matched_indicators)
        seen_indicators = []

        for item in indicators:
            if item['pattern'].lower() in seen_indicators:
                continue
            cur_node = nc.get_node(item["pattern"].lower())
            cur_node = nc.get_node(item["pattern"]) if cur_node is None else cur_node
            if cur_node is None:
                continue
            cur_node.update(trdb_info={**item, 'uid': str(item['uid']),
                                       'security_category': item['security_category'].value,
                                       'pattern_type': item['pattern_type'].value,
                                       'pattern_subtype': item['pattern_subtype'].value})
            if cur_node.group == "Exchange & DEX":
                seen_indicators.append(item['pattern'].lower())
                continue
            if item["security_category"].value == "graylist":
                if item["annotation"]:
                    cur_node.update(annotation=item["annotation"])
                    cur_node.set_group_from_annotation()
                else:
                    cur_node.update(group="No Tag", annotation="")
            else:
                kwargs = {}
                kwargs["group"] = item["security_category"].value.title()
                if item["annotation"]:
                    kwargs["annotation"] = item["annotation"]
                    if "Exchange" in item["annotation"] or "DEX" in item["annotation"]:
                        kwargs["group"] = "Exchange & DEX"
                else:
                    kwargs["annotation"] = ""
                cur_node.update(**kwargs)
            nc.update_node(item['pattern'].lower(), cur_node)
            for transaction in item_list:
                if not transaction.get('sender_annotation', None):
                    transaction['sender_annotation'] = ''
                if not transaction.get('receiver_annotation', None):
                    transaction['receiver_annotation'] = ''

                if transaction['sender'].lower() == cur_node.address:
                    transaction['sender_annotation'] = cur_node.annotation
                elif transaction['receiver'].lower() == cur_node.address:
                    transaction['receiver_annotation'] = cur_node.annotation
            seen_indicators.append(item['pattern'].lower())
        return nc, item_list

    def set_annotations_from_db(self, token_type='ETH'):
        if not self._skip_source and self._async_source_graph:
            tracking_results, nc = self._async_source_graph.get()
            updated_nc, updated_item_list = TrackingResults.update_annotations(nc, tracking_results['item_list'], token_type)
            tracking_results['node_list'] = list(updated_nc.get_nodes_as_dict().values())
            tracking_results['item_list'] = updated_item_list
            updated_nc.filter_update_nodes()
            tracking_results['graph_node_list'] = list(updated_nc.get_nodes_as_dict().values())
            tracking_results['node_enum'] = updated_nc.get_node_enum()
            self._source_graph = tracking_results
        if not self._skip_dist and self._async_dist_graph:
            tracking_results, nc = self._async_dist_graph.get()
            updated_nc, updated_item_list = TrackingResults.update_annotations(nc, tracking_results['item_list'], token_type)
            tracking_results['node_list'] = list(updated_nc.get_nodes_as_dict().values())
            tracking_results['item_list'] = updated_item_list
            updated_nc.filter_update_nodes()
            tracking_results['graph_node_list'] = list(updated_nc.get_nodes_as_dict().values())
            tracking_results['node_enum'] = updated_nc.get_node_enum()
            self._dist_graph = tracking_results

    def make_graph_dict(self):
        graph_dict = {}

        if not self._skip_source and not self._skip_dist and all([self._source_graph, self._dist_graph]):
            track_dist_result = self._dist_graph
            track_source_result = self._source_graph
            graph_dict['item_list'] = track_dist_result['item_list'] + track_source_result['item_list']
            graph_dict['keys'] = track_dist_result['keys']
            pick_dist_graph = track_dist_result['node_list']
            pick_dist_edges = track_dist_result['edge_list']
            pick_src_graph = track_source_result['node_list']
            pick_src_edges = track_source_result['edge_list']
            if track_dist_result['graph_node_list']:
                pick_dist_graph = track_dist_result['graph_node_list']
                pick_dist_edges = track_dist_result['graph_edge_list']
            if track_source_result['graph_node_list']:
                pick_src_graph = track_source_result['graph_node_list']
                pick_src_edges = track_source_result['graph_edge_list']
            # the original node is the first entry in both dist and source so remove duplicates here
            graph_dict['node_list'] = track_dist_result['node_list'] + track_source_result['node_list'][1::]
            graph_dict['graph_node_list'] = pick_dist_graph + pick_src_graph[1::]
            graph_dict['edge_list'] = track_dist_result['edge_list'] + track_source_result['edge_list']
            graph_dict['graph_edge_list'] = pick_dist_edges + pick_src_edges
            graph_dict['node_enum'] = {**track_dist_result['node_enum'], **track_source_result['node_enum']}
            graph_dict['send_count'] = track_dist_result['volume_count_1']
            graph_dict['receive_count'] = track_source_result['volume_count_-1']
        elif not self._skip_dist and self._dist_graph:
            track_dist_result = self._dist_graph
            graph_dict.update(track_dist_result)
            graph_dict['send_count'] = graph_dict.pop('volume_count_1')
        elif not self._skip_source and self._source_graph:
            track_source_result = self._source_graph
            graph_dict.update(track_source_result)
            graph_dict['receive_count'] = graph_dict.pop('volume_count_-1')

        return graph_dict


class BTCTrackingResults(TrackingResults):
    def __init__(self, **kwargs):
        super(BTCTrackingResults, self).__init__(**kwargs)
        self.tx_hash = find_key(kwargs, 'tx_hash')
        self.address = find_key(kwargs, 'wallet_address')

    def fetch_results(self, tx_limit, limit, save_to_db, for_source=False):
        external_api_client = LyzeAPIInterface(settings.LYZE_API_KEY)
        if for_source:
            depth_limit = self.source_depth if self.source_depth < 3 else 2
        else:
            depth_limit = self.distribution_depth if self.distribution_depth < 3 else 2
        transaction_data = external_api_client.get_transactions(self.address, limit, self.tx_hash, depth_limit, for_source)
        self.ext_api_calls += 1
        if not transaction_data:
            error_key = "source" if for_source else "distribution"
            self.error_messages[error_key] = "Missing {} results for the wallet address within the date range " \
                                             "specified".format(error_key)
        return transaction_data

    def get_tracking_data(self, tx_limit, limit, save_to_db):
        pool = ThreadPool(processes=2)
        if self.source_depth:
            self._skip_source = False
            self._async_source_result = pool.apply_async(self.fetch_results, (tx_limit, limit, save_to_db, True),
                                                         callback=self.bloxy_response_callback)
        if self.distribution_depth:
            self._skip_dist = False
            self._async_dist_result = pool.apply_async(self.fetch_results, (tx_limit, limit, save_to_db, False),
                                                       callback=self.bloxy_response_callback)
        pool.close()
        pool.join()

    def create_graph_data(self, wallet_address=None):
        pool = Pool(processes=2)
        if not self._skip_source:
            source_result = self._async_source_result.get()
            if source_result:
                self._async_source_graph = pool.apply_async(generate_nodes_edges_btc, (source_result, -1, wallet_address))
        if not self._skip_dist:
            dist_result = self._async_dist_result.get()
            if dist_result:
                self._async_dist_graph = pool.apply_async(generate_nodes_edges_btc, (dist_result, 1, wallet_address))
        pool.close()
        pool.join()


class BTCCoinpathTrackingResults(TrackingResults):
    def __init__(self, **kwargs):
        super(BTCCoinpathTrackingResults, self).__init__(**kwargs)

    def fetch_results(self, tx_limit, limit, save_to_db, for_source=False):
        external_api_client = BloxyBTCAPIInterface(settings.BLOXY_API_KEY)
        depth_limit = self.source_depth if for_source else self.distribution_depth
        from_time = self.from_date
        till_date_extend = self.to_date + "T23:59:59"
        transaction_data = external_api_client.get_transactions(self.wallet_address, tx_limit, limit,
                                                                depth_limit, till_time=till_date_extend,
                                                                source=for_source, from_time=from_time)
        self.ext_api_calls += 1
        if not transaction_data:
            error_key = "source" if for_source else "distribution"
            self.error_messages[error_key] = "Missing {} results for the wallet address within the date range " \
                                             "specified".format(error_key)
        return transaction_data

    def get_tracking_data(self, tx_limit, limit, save_to_db):
        pool = ThreadPool(processes=2)
        if self.source_depth:
            self._skip_source = False
            self._async_source_result = pool.apply_async(self.fetch_results, (tx_limit, limit, save_to_db, True),
                                                         callback=self.bloxy_response_callback)
        if self.distribution_depth:
            self._skip_dist = False
            self._async_dist_result = pool.apply_async(self.fetch_results, (tx_limit, limit, save_to_db, False),
                                                       callback=self.bloxy_response_callback)
        pool.close()
        pool.join()

    def create_graph_data(self):
        pool = Pool(processes=2)
        if not self._skip_source:
            source_result = self._async_source_result.get()
            if source_result:
                self._async_source_graph = pool.apply_async(generate_nodes_edges_coinpath, (source_result, -1))
        if not self._skip_dist:
            dist_result = self._async_dist_result.get()
            if dist_result:
                self._async_dist_graph = pool.apply_async(generate_nodes_edges_coinpath, (dist_result, 1))
        pool.close()
        pool.join()


class EthPathResults(TrackingResults):
    def __init__(self, **kwargs):
        super(EthPathResults, self).__init__(**kwargs)
        self.address_from = kwargs['address_from']
        self.address_to = kwargs['address_to']
        self.depth_limit = kwargs['depth']
        self.min_tx_amount = kwargs['min_tx_amount']
        self.limit_address_tx = kwargs['limit_address_tx']
        self._external_api_client = BloxyEthAPIInterface(settings.BLOXY_API_KEY, settings.BLOXY_ETHCOINPATH_ENDPOINT)
        self._graph_func = generate_nodes_edges_ethcoinpath

    def fetch_results(self, tx_limit, limit, save_to_db, for_source=False):
        transaction_data = self._external_api_client.get_path_transactions(self)
        self.ext_api_calls += 1
        if not transaction_data:
            error_key = "distribution"
            self.error_messages[error_key] = "Missing {} results for the wallet address within the date range " \
                                             "specified".format(error_key)
        return transaction_data

    def get_tracking_data(self, tx_limit=None, limit=None, save_to_db=False):
        pool = ThreadPool(processes=1)
        if self.depth_limit:
            self._skip_dist = False
            self._async_dist_result = pool.apply_async(self.fetch_results, (tx_limit, limit, save_to_db, False),
                                                       callback=self.bloxy_response_callback)
        pool.close()
        pool.join()

    def create_graph_data(self):
        pool = Pool(processes=1)
        if not self._skip_dist:
            dist_result = self._async_dist_result.get()
            if dist_result:
                self._async_dist_graph = pool.apply_async(self._graph_func, (dist_result, 1))
        pool.close()
        pool.join()


class BtcPathResults(EthPathResults):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._external_api_client = BloxyEthAPIInterface(settings.BLOXY_API_KEY, settings.BLOXY_BTCCOINPATH_ENDPOINT)
        self._graph_func = generate_nodes_edges_btccoinpath
