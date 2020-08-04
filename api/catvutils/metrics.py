from collections import defaultdict
from itertools import groupby
from operator import gt

from django.utils.timezone import now

from api.catvutils.tracking_results import chunks
from api.models import IndicatorExtraAnnotation

__all__ = ('CatvMetrics',)

def pick_n_unique(iterable, key, n):
    seen = []
    n_list = []
    for item in iterable:
        if len(n_list) == n:
            return n_list
        if item[key] not in seen:
            n_list.append(item)
            seen.append(item[key])
    return n_list


class CatvMetrics:
    def __init__(self, data):
        self.item_list = data.get("item_list", [])
        self.node_list = data.get("node_list", [])
        self.edge_list = data.get("edge_list", [])
        self.seg_item_list = []
        self.seg_node_list = []
        
    def generate_metrics(self, compare_operator):
        self.seg_item_list = list(filter(lambda item: compare_operator(item["depth"], 0), self.item_list))
        self.seg_node_list = list(filter(lambda node: compare_operator(node["level"], 0), self.node_list))
        if not self.seg_node_list:
            return {
                "blacklisted": [],
                "exchange": [],
                "depth_breakdown": {},
                "max_sender": {},
                "max_receiver": {}
            }
        # top 10 blacklisted wallets by balance
        black_wallets = list(filter(lambda node: node["group"] == 'Blacklist', self.seg_node_list))
        black_wallets_top = sorted(black_wallets, key=lambda wallet: wallet["balance"], reverse=True)
        black_wallets_top = pick_n_unique(black_wallets_top, "address", 10)
        black_wallets_top = [{"address": wallet["address"], "balance": wallet["balance"]} for wallet in black_wallets_top]
        # top 10 exchange wallets by balance
        exchange_wallets = list(filter(lambda node: node["group"] == 'Exchange & DEX', self.seg_node_list))
        exchange_wallets_top = sorted(exchange_wallets, key=lambda wallet: wallet["amount_in"], reverse=True)[:15]
        exchange_wallets_clean = {}
        skip_words = (["exchange", "wallet", "exchange wallet", "user wallet", "fiat gateway",
                       "proxy contract", "defi", "dex"
                       ])
        for wallet in exchange_wallets_top:
            word_list = wallet["annotation"].split(",")
            word_list = [w.strip() for w in word_list]
            clean_name = next((word for word in word_list
                               if word.lower() not in skip_words),
                              "Generic")
            clean_name = clean_name.replace("_", " ")
            clean_name = clean_name.split(" ")[0]
            if clean_name != "Generic":
                # Dictionaries are guaranteed to preserve insert order in Python 3.6
                exchange_wallets_clean[clean_name] = clean_name
        # group wallets by level
        grouped_by_depth = groupby(self.seg_item_list, lambda item: str(item["depth"]))
        highest_by_depth = defaultdict(dict)
        # highest received, sent tx_hash per level
        for level, items in grouped_by_depth:
            max_sent_item = max(items, key=lambda item: item["amount"])
            highest_by_depth[level]["sent"] = {"tx_hash": max_sent_item["tx_hash"], "amount": max_sent_item["amount"]}
            int_level = abs(int(level))
            if int_level > 1:
                depth_key = str(int_level-1)
                depth_key = depth_key if compare_operator == gt else f"-{depth_key}"
                highest_by_depth[depth_key]["received"] = {"tx_hash": max_sent_item["tx_hash"], "amount": max_sent_item["amount"]}
        # wallet with highest amount sent
        grouped_by_sender = defaultdict(list)
        grouped_by_receiver = defaultdict(list)
        for item in self.seg_item_list:
            grouped_by_sender[item["sender"]].append(item)
            grouped_by_receiver[item["receiver"]].append(item)
        grouped_by_sender = [{
            "address": sender,
            "amount": sum([item["amount"] if abs(item["depth"]) > 1 else 0 for item in items])}
                             for sender, items in grouped_by_sender.items()]
        max_sender = max(grouped_by_sender, key=lambda sender: sender["amount"])
        # wallet with highest amount received
        grouped_by_receiver = [{
            "address": receiver,
            "amount": sum([item["amount"] if abs(item["depth"]) > 1 else 0 for item in items])}
                               for receiver, items in grouped_by_receiver.items()]
        max_receiver = max(grouped_by_receiver, key=lambda receiver: receiver["amount"])
        # create dictionary and return
        return {
            "blacklisted": black_wallets_top,
            "exchange": list(exchange_wallets_clean.keys())[:10],
            "depth_breakdown": dict(highest_by_depth),
            "max_sender": max_sender,
            "max_receiver": max_receiver
        }
    
    def save_annotations(self):
        all_nodes = {node["address"]: node for node in self.node_list}
        all_node_keys = list(all_nodes.keys())
        for node_chunk in chunks(all_node_keys, 2000):
            bulk_indicators = []
            matched_nodes = IndicatorExtraAnnotation.objects.filter(pattern__in=node_chunk)
            matched_nodes_addr = [node.pattern for node in matched_nodes]
            missing_nodes_addr = set(node_chunk) - set(matched_nodes_addr)
            for matched_node in matched_nodes:
                matched_node.annotation = all_nodes[matched_node.pattern]["annotation"]
                matched_node.updated = now()
            for missing in missing_nodes_addr:
                bulk_indicators.append(
                    IndicatorExtraAnnotation(pattern=missing, annotation=all_nodes[missing]["annotation"])
                )
            IndicatorExtraAnnotation.objects.bulk_create(bulk_indicators)
            IndicatorExtraAnnotation.objects.bulk_update(matched_nodes, update_fields=['annotation', 'updated'])


