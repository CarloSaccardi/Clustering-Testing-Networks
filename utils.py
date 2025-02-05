import requests, zipfile, io
import numpy as np
import torch
import networkx as nx
from sklearn.metrics import confusion_matrix
from scipy.optimize import linear_sum_assignment as linear_assignment
import matplotlib.pyplot as plt

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.neighbors import kneighbors_graph
from scipy import sparse
from scipy import linalg

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

def download_datasets():
    dataset_links = ['http://www.chrsmrrs.com/graphkerneldatasets/ENZYMES.zip', 'https://www.chrsmrrs.com/graphkerneldatasets/deezer_ego_nets.zip', 'https://www.chrsmrrs.com/graphkerneldatasets/facebook_ct1.zip',
                     'https://www.chrsmrrs.com/graphkerneldatasets/github_stargazers.zip', 'https://www.chrsmrrs.com/graphkerneldatasets/REDDIT-BINARY.zip','https://www.chrsmrrs.com/graphkerneldatasets/OHSU.zip',
                     'https://www.chrsmrrs.com/graphkerneldatasets/Peking_1.zip','https://www.chrsmrrs.com/graphkerneldatasets/KKI.zip', 'https://www.chrsmrrs.com/graphkerneldatasets/PROTEINS.zip']
    for l in dataset_links:
        r = requests.get(l)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        z.extractall()


# taken from https://github.com/JiaxuanYou/graph-generation/blob/3444b8ad2fd7ecb6ade45086b4c75f8e2e9f29d1/data.py#L24
def load_graph(min_num_nodes=10, name='ENZYMES'):
    print('Loading graph dataset: ' + str(name))
    G = nx.Graph()
    # load data
    path = name + '/'
    data_adj = np.loadtxt(path + name + '_A.txt', delimiter=',').astype(int)
    data_graph_indicator = np.loadtxt(path + name + '_graph_indicator.txt', delimiter=',').astype(int)
    data_tuple = list(map(tuple, data_adj))

    # add edges
    G.add_edges_from(data_tuple)
    G.remove_nodes_from(list(nx.isolates(G)))

    # split into graphs
    graph_num = data_graph_indicator.max()
    node_list = np.arange(data_graph_indicator.shape[0]) + 1
    graphs = []
    # nx_graphs = []
    max_nodes = 0
    all_nodes = []
    for i in range(graph_num):
        # find the nodes for each graph
        nodes = node_list[data_graph_indicator == i + 1]
        G_sub = G.subgraph(nodes)
        if G_sub.number_of_nodes() >= min_num_nodes:
            adj = nx.adjacency_matrix(G_sub)
            adj = adj.todense()
            adj = torch.Tensor(np.asarray(adj)).to(device=device)
            graphs.append(adj)
            if G_sub.number_of_nodes() > max_nodes:
                max_nodes = G_sub.number_of_nodes()
            all_nodes.append(G_sub.number_of_nodes())
    print('Loaded and the total number of graphs are ', len(graphs))
    print('max num of nodes is ', max_nodes)
    print('total graphs ', len(graphs))
    print('histogram of number of nodes in ', name)
    #print(all_nodes)
    plt.hist(all_nodes)
    plt.show()
    return graphs#list of adj matrixes. The lenght of the list is the number of subgraphs

def kmeans_dist(dist, num_clusters=2):
    w,v = torch.eig(dist,eigenvectors=True)
    w_real = w[:,0] #symmetric matrix so no need to bother about the complex part
    sorted_w = torch.argsort(-torch.abs(w_real))
    to_pick_idx = sorted_w[:num_clusters]
    eig_vec = v[:,to_pick_idx]
    eig_vec = eig_vec.cpu().detach().numpy()
    kmeans = KMeans(n_clusters=num_clusters, random_state=0).fit(eig_vec)
    return kmeans.labels_

#hungarian algorithm
def _make_cost_m(cm):
    s = np.max(cm)
    return (- cm + s)

def error(gt_real, labels):
    cm = confusion_matrix(gt_real, labels)
    indexes = linear_assignment(_make_cost_m(cm)) #Hungarian algorithm
    js = [e[1] for e in sorted(indexes, key=lambda x: x[0])]
    cm2 = cm[:, js]
    err = 1 - np.trace(cm2) / np.sum(cm2)
    return err

#spectral clustering
def generate_graph_laplacian(df, nn):
    """Generate graph Laplacian from data."""
    # Adjacency Matrix.
    connectivity = kneighbors_graph(X=df, n_neighbors=nn, mode='connectivity')
    adjacency_matrix_s = (1 / 2) * (connectivity + connectivity.T)
    # Graph Laplacian.
    graph_laplacian_s = sparse.csgraph.laplacian(csgraph=adjacency_matrix_s, normed=False)
    graph_laplacian = graph_laplacian_s.toarray()
    return graph_laplacian


# We project onto the real numbers.
def compute_spectrum_graph_laplacian(graph_laplacian):
    """Compute eigenvalues and eigenvectors and project
    them onto the real numbers.
    """
    eigenvals, eigenvcts = linalg.eig(graph_laplacian)
    eigenvals = np.real(eigenvals)
    eigenvcts = np.real(eigenvcts)
    return eigenvals, eigenvcts


def spectral_clustering(affinity_mat, num_clusters=3):
    graph_laplacian = generate_graph_laplacian(df=affinity_mat, nn=8)
    eigenvals, eigenvcts = compute_spectrum_graph_laplacian(graph_laplacian)

    eigenvals_sorted_indices = np.argsort(eigenvals)
    eigenvals_sorted = eigenvals[eigenvals_sorted_indices]

    zero_eigenvals_index = np.argwhere(abs(eigenvals) < 1e+0)
    # eigenvals[zero_eigenvals_index]

    proj_df = pd.DataFrame(eigenvcts[:, eigenvals_sorted_indices[:num_clusters]])  # zero_eigenvals_index.squeeze()])
    k_means = KMeans(random_state=25, n_clusters=num_clusters)
    k_means.fit(proj_df)
    labels = k_means.predict(proj_df)

    return labels

#graphons for simulated data
def graphon_1(x):
    p = torch.zeros((x.shape[0],x.shape[0]), dtype=torch.float64).to(device=device)
    u = p + x.reshape(1, -1)
    v = p + x.reshape(-1, 1)
    graphon = u * v
    return graphon

def graphon_2(x):
    p = torch.zeros((x.shape[0],x.shape[0]), dtype=torch.float64).to(device=device)
    u = p + x.reshape(1, -1)
    v = p + x.reshape(-1, 1)
    graphon = torch.exp(-torch.pow(torch.max(u,v),0.75))
    return graphon

def graphon_3(x):
    p = torch.zeros((x.shape[0],x.shape[0]), dtype=torch.float64).to(device=device)
    u = p + x.reshape(1, -1)
    v = p + x.reshape(-1, 1)
    graphon = torch.exp(-0.5* (torch.min(u,v) + torch.pow(u,0.5) + torch.pow(v,0.5)))
    return graphon

def graphon_4(x):
    p = torch.zeros((x.shape[0],x.shape[0]), dtype=torch.float64).to(device=device)
    u = p + x.reshape(1, -1)
    v = p + x.reshape(-1, 1)
    graphon = torch.abs(u-v)
    return graphon


def generate_graphs(graphon_key, n):
    graph_gen = []

    for nn in n:
        x = torch.distributions.uniform.Uniform(0, 1).sample([nn]).to(device=device)
        if graphon_key == 1:
            graph_prob = graphon_1(x)
        elif graphon_key == 2:
            graph_prob = graphon_2(x)
        elif graphon_key == 3:
            graph_prob = graphon_3(x)
        elif graphon_key == 4:
            graph_prob = graphon_4(x)
        else:
            print('Wrong key')
            exit()

        graph = torch.distributions.binomial.Binomial(1, graph_prob).sample()
        graph = torch.triu(graph, diagonal=1)
        graph = graph + graph.t()
        graph_gen.append(graph)

    return graph_gen


def data_simulation(graphons, number_of_graphs=10, start=100, stop=1000):
    graphs = []
    labels = []
    for graphon in graphons:
        p = torch.randperm(stop)
        n = p[p > start][:number_of_graphs]
        print('nodes ', n)
        g = generate_graphs(graphon, n)
        graphs = graphs + g

    for i in range(len(graphons)):
        l = i * np.ones(number_of_graphs)
        labels = labels + l.tolist()
    print('graphs generated', len(graphs))
    print('true labels ', labels)
    return graphs, labels



if __name__ == "__main__":
    graphs = load_graph(min_num_nodes=10, name='REDDIT-BINARY')
    a=1
    
    
