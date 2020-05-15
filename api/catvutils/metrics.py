from itertools import groupby


class CatvMetrics:
    def __init__(self, data):
        self.item_list = data.get("item_list", [])
        self.node_list = data.get("node_list", [])
        self.edge_list = data.get("edge_list", [])
        self.dist_item_list = []
        self.dist_node_list = []
        self.dist_edge_list = []
        self.src_item_list = []
        self.src_node_list = []
        self.src_edge_list = []
        
    def generate_dist_metrics(self):
        self.dist_item_list = filter(lambda item: item["depth"] > 0, self.item_list)
        self.dist_node_list = filter(lambda node: node["level"] > 0, self.node_list)
        self.dist_edge_list = filter(lambda edge: edge["to"] > 0, self.edge_list)
        black_wallets = list(filter(lambda node: node["group"] == 'Blacklist', self.dist_node_list))
        black_wallets_top = sorted(black_wallets, key=lambda wallet: wallet["balance"])[:10]
        black_wallets_top = [{"address": wallet["address"], "balance": wallet["balance"]} for wallet in black_wallets_top]
        exchange_wallets = list(filter(lambda node: node["group"] == 'Exchange & DEX', self.dist_node_list))
        exchange_wallets_top = sorted(exchange_wallets, key=lambda wallet: wallet["balance"])[:10]
        exchange_wallets_clean = []
        for wallet in exchange_wallets_top:
            word_list = wallet["annotation"].split(", ")
            clean_name = next((word for word in word_list if word not in ["Exchange", "Wallet"] and word.isalpha()), "Generic Exchange")
            exchange_wallets_clean.append({
                "name": clean_name,
                "address": wallet["address"],
                "balance": wallet["balance"]})
        grouped_by_depth = groupby(self.dist_item_list, lambda item: str(item["depth"]))
        highest_sent_by_depth = {}
        highest_received_by_depth = {}
        # generate level 1 highest received
        for level, items in grouped_by_depth:
            max_sent_item = max(items, key=lambda item: item["amount"])
            highest_sent_by_depth[level] = max_sent_item["tx_hash"]
            int_level = int(level)
            if int_level > 1:
                highest_received_by_depth[level-1] = max_sent_item["tx_hash"]
                    
        
    def generate_src_metrics(self):
        self.src_item_list = filter(lambda item: item["depth"] < 0, self.item_list)
        self.src_node_list = filter(lambda node: node["level"] < 0, self.node_list)
        self.src_edge_list = filter(lambda edge: edge["to"] < 0, self.edge_list)
    