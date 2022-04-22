from multiprocessing.pool import ThreadPool

class ProcessNodeList:
    def __init__(self, node_list, depths):
        self.node_list = node_list
        self.src_depth = int(depths.split(" / ")[0])
        self.dist_depth = int(depths.split(" / ")[1])
        self._async_src_nodes_by_level = []
        self._async_dist_nodes_by_level = []
        self.src_nodes = []
        self.dist_nodes = []


    def create_node_list_by_depth(self):
        pool = ThreadPool(processes=2)

        if self.src_depth > 0:
            self.src_nodes = [node for node in self.node_list if node['level'] < 0]
            self._async_src_nodes_by_level = pool.apply_async(self.process_node_list, ('src',)).get()

        if self.dist_depth > 0:
            self.dist_nodes = [node for node in self.node_list if node['level'] > 0]
            self._async_dist_nodes_by_level = pool.apply_async(self.process_node_list, ('dist',)).get()

        pool.close()
        pool.join()

    def process_node_list(self, mode):
        if mode == 'dist':
            dist_nodes_by_level = []
            dist_level = 0

            while dist_level <= self.dist_depth:
                temp_dist_node_list = [dist_node for dist_node in self.dist_nodes if dist_node['level'] == dist_level]
                dist_nodes_by_level.append(temp_dist_node_list)
                dist_level = dist_level + 1
            return dist_nodes_by_level

        if mode == 'src':
            src_nodes_by_level = []
            src_level = 0
            while src_level <= self.src_depth:
                temp_src_node_list = [src_node for src_node in self.src_nodes if abs(src_node['level']) == src_level]
                src_nodes_by_level.append(temp_src_node_list)
                src_level = src_level + 1  
            return src_nodes_by_level  

    def get_src_node_lists(self):
        return self._async_src_nodes_by_level

    def get_dist_node_lists(self):
        return self._async_dist_nodes_by_level
