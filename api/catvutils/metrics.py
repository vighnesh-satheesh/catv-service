from collections import defaultdict
from itertools import groupby

from api.models import IndicatorExtraAnnotation

__all__ = ('CatvMetrics',)


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
        # top 10 blacklisted wallets by balance
        black_wallets = list(filter(lambda node: node["group"] == 'Blacklist', self.seg_node_list))
        black_wallets_top = sorted(black_wallets, key=lambda wallet: wallet["balance"])[:10]
        black_wallets_top = [{"address": wallet["address"], "balance": wallet["balance"]} for wallet in black_wallets_top]
        # top 10 exchange wallets by balance
        exchange_wallets = list(filter(lambda node: node["group"] == 'Exchange & DEX', self.seg_node_list))
        exchange_wallets_top = sorted(exchange_wallets, key=lambda wallet: wallet["balance"])
        exchange_wallets_clean = set()
        for wallet in exchange_wallets_top:
            word_list = wallet["annotation"].split(", ")
            clean_name = next((word for word in word_list
                               if word not in ["Exchange", "Wallet"] and (word.isalpha() or word.find(".") != -1)),
                              "Generic Exchange")
            exchange_wallets_clean.add(clean_name)
        # group wallets by level
        grouped_by_depth = groupby(self.seg_item_list, lambda item: str(item["depth"]))
        highest_by_depth = defaultdict(dict)
        # highest received, sent tx_hash per level
        for level, items in grouped_by_depth:
            max_sent_item = max(items, key=lambda item: item["amount"])
            highest_by_depth[level]["sent"] = {"tx_hash": max_sent_item["tx_hash"], "amount": max_sent_item["amount"]}
            int_level = abs(int(level))
            if int_level > 1:
                highest_by_depth[str(int_level-1)]["received"] = {"tx_hash": max_sent_item["tx_hash"], "amount": max_sent_item["amount"]}
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
            "exchange": list(exchange_wallets_clean),
            "depth_breakdown": dict(highest_by_depth),
            "max_sender": max_sender,
            "max_receiver": max_receiver
        }
    
    def save_annotations(self):
        bulk_indicators = []
        for node in self.node_list:
            annotation = node["annotation"]
            if annotation:
               bulk_indicators.append(
                   IndicatorExtraAnnotation(pattern=node["address"], annotation=annotation)
               )
        IndicatorExtraAnnotation.objects.bulk_create(bulk_indicators)

