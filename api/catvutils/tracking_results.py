from multiprocessing.pool import ThreadPool
from multiprocessing import Pool
from datetime import datetime

from django.utils.timezone import make_aware
from django.conf import settings
from django.db.models import Q
from django.db.models.functions import Lower

from .bloxy_interface import BloxyAPIInterface
from .graphtools import generate_nodes_edges
from ..models import BloxyDistribution, BloxySource, Indicator, CaseStatus


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

    def bloxy_response_callback(self, *args, **kwargs):
        if args and 'error' in args[0]:
            self.error = args[0]['error']

    def get_results_from_bloxy(self, bloxy_interface, depth, till_date, for_source=False):
        return bloxy_interface.get_transactions(self.wallet_address, depth,
                                                self.from_date, till_date, self.token_address,
                                                source=for_source)

    def save_bloxy_result(self, bloxy_db_class, depth, from_date, to_date, result):
        bloxy_db_class(address=self.wallet_address, depth_limit=depth, transaction_limit=self.transaction_limit,
                       from_time=from_date, till_time=to_date, result=result,
                       token_address=self.token_address, updated=make_aware(datetime.now())).save()

    def fetch_results(self, for_source=False):
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
                transaction_data = self.get_results_from_bloxy(bloxy, depth_limit, till_date_extend, for_source)
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
                    transaction_data = self.get_results_from_bloxy(bloxy, depth_limit, till_date_extend, for_source)
                    if len(transaction_data) == 0:
                        raise IndexError
                    self.save_bloxy_result(bloxy_db_class, depth_limit, aware_from_date, aware_to_date,
                                           transaction_data)
                    self.ext_api_calls += 1
                else:
                    transaction_data = db_results[0]['result']
            return transaction_data
        except IndexError:
            raise IndexError("This address has missing {} results.".format(error_placeholder))

    def get_tracking_data(self):
        pool = ThreadPool(processes=2)
        if self.source_depth:
            self._skip_source = False
            self._async_source_result = pool.apply_async(self.fetch_results, (True,),
                                                         callback=self.bloxy_response_callback)
        if self.distribution_depth:
            self._skip_dist = False
            self._async_dist_result = pool.apply_async(self.fetch_results, (False,),
                                                       callback=self.bloxy_response_callback)
        pool.close()
        pool.join()

    def create_graph_data(self):
        pool = Pool(processes=2)
        if not self._skip_source:
            source_result = self._async_source_result.get()
            self._async_source_graph = pool.apply_async(generate_nodes_edges, (source_result, -1,))

        if not self._skip_dist:
            dist_result = self._async_dist_result.get()
            self._async_dist_graph = pool.apply_async(generate_nodes_edges, (dist_result, 1,))
        pool.close()
        pool.join()

    @staticmethod
    def update_annotations(nc, item_list):
        addr_list = nc.get_node_enum().keys()
        query_list = Q(cases__status__in=[CaseStatus.RELEASED], pattern_subtype="ETH", pattern_type="cryptoaddr")
        query_list &= Q(pattern_lower__in=[addr.lower() for addr in addr_list])
        indicators = Indicator.objects.annotate(pattern_lower=Lower('pattern')).filter(query_list).distinct('id').\
            values('id', 'uid', 'security_category', 'security_tags', 'pattern', 'detail', 'pattern_subtype',
                   'pattern_type', 'annotation').order_by('-id')
        seen_indicators = []

        for item in indicators:
            if item['pattern'].lower() in seen_indicators:
                continue

            cur_node = nc.get_node(item["pattern"].lower())
            cur_node.update(trdb_info={**item, 'uid': str(item['uid']),
                                       'security_category': item['security_category'].value,
                                       'pattern_type': item['pattern_type'].value,
                                       'pattern_subtype': item['pattern_subtype'].value})
            if cur_node.group == "Exchange & DEX":
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
                transaction.update((k + "_annotation", cur_node.annotation) for k, v in transaction.items()
                                   if (k == 'sender' or k == 'receiver') and v.lower() == cur_node.address)
            seen_indicators.append(item['pattern'].lower())
        return nc, item_list

    def set_annotations_from_db(self):
        if not self._skip_source:
            tracking_results, nc = self._async_source_graph.get()
            updated_nc, updated_item_list = TrackingResults.update_annotations(nc, tracking_results['item_list'])
            tracking_results['node_list'] = list(updated_nc.get_nodes_as_dict().values())
            tracking_results['item_list'] = updated_item_list
            self._source_graph = tracking_results
        if not self._skip_dist:
            tracking_results, nc = self._async_dist_graph.get()
            updated_nc, updated_item_list = TrackingResults.update_annotations(nc, tracking_results['item_list'])
            tracking_results['node_list'] = list(updated_nc.get_nodes_as_dict().values())
            tracking_results['item_list'] = updated_item_list
            self._dist_graph = tracking_results

    def make_graph_dict(self):
        graph_dict = {}

        if not self._skip_source and not self._skip_dist:
            track_dist_result = self._dist_graph
            track_source_result = self._source_graph
            graph_dict['item_list'] = track_dist_result['item_list'] + track_source_result['item_list']
            graph_dict['keys'] = track_dist_result['keys']
            # the original node is the first entry in both dist and source so remove duplicates here
            graph_dict['node_list'] = track_dist_result['node_list'] + track_source_result['node_list'][1::]
            graph_dict['edge_list'] = track_dist_result['edge_list'] + track_source_result['edge_list']
            graph_dict['node_enum'] = {**track_dist_result['node_enum'], **track_source_result['node_enum']}
            graph_dict['send_count'] = track_dist_result['volume_count_1']
            graph_dict['receive_count'] = track_source_result['volume_count_-1']
        elif not self._skip_dist:
            track_dist_result = self._dist_graph
            graph_dict.update(track_dist_result)
            graph_dict['send_count'] = graph_dict.pop('volume_count_1')
        elif not self._skip_source:
            track_source_result = self._source_graph
            graph_dict.update(track_source_result)
            graph_dict['receive_count'] = graph_dict.pop('volume_count_-1')

        return graph_dict
