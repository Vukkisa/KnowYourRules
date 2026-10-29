## Split: test

| chunker | embedder | retrieval | rerank | mrr | recall@4 | ndcg@4 | precision@4 | hit@1 | context_chars@4 | auroc_answerable | latency_ms_mean |
|---|---|---|---|---|---|---|---|---|---|---|---|
| structure | bge-small-en-v1.5 | rrf(dense+bm25) | bge-reranker-base@20 | 0.897 | 0.938 | 0.903 | 0.242 | 0.844 | 1972.031 | 0.945 | 2184.882 |
| structure | nomic+prefix | rrf(dense+bm25) | bge-reranker-base@20 | 0.897 | 0.938 | 0.903 | 0.242 | 0.844 | 1979.219 | 0.945 | 1912.339 |
| structure | nomic+prefix | dense | bge-reranker-base@20 | 0.896 | 0.938 | 0.903 | 0.242 | 0.844 | 1952.219 | 0.945 | 2405.939 |
| structure | bge-small-en-v1.5 | dense | bge-reranker-base@20 | 0.896 | 0.938 | 0.903 | 0.242 | 0.844 | 1959.125 | 0.945 | 1692.449 |
| structure | nomic+prefix | dense | none | 0.872 | 0.969 | 0.885 | 0.258 | 0.781 | 1878.531 | 0.898 | 47.356 |
| provision-contextual | nomic+prefix | dense | bge-reranker-base@20 | 0.872 | 0.938 | 0.883 | 0.242 | 0.812 | 2242.844 | 0.938 | 1919.449 |
| provision-contextual | nomic+prefix | rrf(dense+bm25) | bge-reranker-base@20 | 0.872 | 0.938 | 0.883 | 0.242 | 0.812 | 2241.875 | 0.938 | 1762.722 |
| provision-contextual | bge-small-en-v1.5 | rrf(dense+bm25) | bge-reranker-base@20 | 0.872 | 0.938 | 0.883 | 0.242 | 0.812 | 2227.750 | 0.938 | 2104.397 |
| provision-contextual | bge-small-en-v1.5 | dense | bge-reranker-base@20 | 0.871 | 0.938 | 0.883 | 0.242 | 0.812 | 2226.969 | 0.938 | 2607.884 |
| fixed-500/100 | nomic+prefix | dense | none | 0.870 | 0.906 | 0.846 | 0.281 | 0.812 | 1565.844 | 0.906 | 48.815 |
| structure | nomic (baseline) | dense | none | 0.857 | 0.969 | 0.880 | 0.258 | 0.750 | 1821.469 | 0.898 | 36.968 |
| structure | bge-small-en-v1.5 | dense | none | 0.855 | 0.938 | 0.872 | 0.250 | 0.781 | 1899.156 | 0.938 | 29.810 |
| sentence-600 | nomic (baseline) | dense | none | 0.851 | 0.906 | 0.817 | 0.289 | 0.750 | 2071.750 | 0.914 | 37.049 |
| sentence-600 | nomic+prefix | dense | none | 0.851 | 0.906 | 0.825 | 0.297 | 0.781 | 2066.125 | 0.883 | 46.749 |
| fixed-1000/200 (baseline) | nomic+prefix | dense | bge-reranker-base@20 | 0.849 | 0.906 | 0.856 | 0.234 | 0.781 | 3068.750 | 0.938 | 1979.418 |
| fixed-1000/200 (baseline) | nomic+prefix | rrf(dense+bm25) | bge-reranker-base@20 | 0.849 | 0.906 | 0.856 | 0.234 | 0.781 | 3068.750 | 0.938 | 2278.491 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | dense | bge-reranker-base@20 | 0.849 | 0.906 | 0.856 | 0.234 | 0.781 | 3068.750 | 0.938 | 1588.225 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | rrf(dense+bm25) | bge-reranker-base@20 | 0.849 | 0.906 | 0.856 | 0.234 | 0.781 | 3068.750 | 0.938 | 1698.184 |
| provision-contextual | bge-small-en-v1.5 | dense | none | 0.848 | 0.938 | 0.866 | 0.250 | 0.750 | 2225.594 | 0.945 | 29.822 |
| fixed-1000/200 (baseline) | nomic (baseline) | hybrid-0.5 | none | 0.845 | 0.922 | 0.852 | 0.242 | 0.750 | 3036.031 | 0.938 | 36.583 |
| sentence-600 | bge-small-en-v1.5 | dense | none | 0.843 | 0.891 | 0.832 | 0.297 | 0.781 | 2080.688 | 0.930 | 29.796 |
| fixed-500/100 | bge-small-en-v1.5 | dense | none | 0.837 | 0.891 | 0.822 | 0.266 | 0.781 | 1384.469 | 0.930 | 30.055 |
| fixed-1000/200 (baseline) | nomic+prefix | hybrid-0.5 | none | 0.833 | 0.922 | 0.846 | 0.242 | 0.750 | 3029.125 | 0.883 | 47.373 |
| provision-contextual | nomic (baseline) | dense | none | 0.833 | 0.969 | 0.864 | 0.258 | 0.719 | 2222.219 | 0.875 | 37.050 |
| fixed-1000/200 (baseline) | nomic+prefix | rrf(dense+bm25) | none | 0.831 | 0.906 | 0.840 | 0.242 | 0.750 | 3025.562 | 0.867 | 51.485 |
| fixed-1000/200 (baseline) | nomic+prefix | dense | none | 0.829 | 0.922 | 0.843 | 0.242 | 0.719 | 3061.625 | 0.844 | 47.340 |
| provision-contextual | nomic+prefix | dense | none | 0.828 | 0.969 | 0.857 | 0.258 | 0.688 | 2170.188 | 0.867 | 46.665 |
| fixed-1000/200 (baseline) | nomic (baseline) | rrf(dense+bm25) | none | 0.827 | 0.891 | 0.829 | 0.234 | 0.719 | 3038.188 | 0.914 | 37.822 |
| structure | nomic+prefix | hybrid-0.5 | none | 0.824 | 0.938 | 0.836 | 0.250 | 0.719 | 1837.625 | 0.914 | 47.383 |
| fixed-500/100 | nomic (baseline) | dense | none | 0.821 | 0.875 | 0.792 | 0.250 | 0.750 | 1520.000 | 0.898 | 37.756 |
| fixed-1000/200 (baseline) | nomic (baseline) | dense | none | 0.818 | 0.922 | 0.834 | 0.242 | 0.688 | 3004.719 | 0.867 | 36.572 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | dense | none | 0.816 | 0.844 | 0.805 | 0.219 | 0.750 | 3083.062 | 0.906 | 29.572 |
| sentence-600 | nomic (baseline) | hybrid-0.5 | none | 0.812 | 0.875 | 0.776 | 0.273 | 0.719 | 2088.031 | 0.953 | 37.067 |
| structure | nomic (baseline) | hybrid-0.5 | none | 0.807 | 0.938 | 0.831 | 0.250 | 0.688 | 1840.750 | 0.930 | 36.983 |
| sentence-600 | nomic+prefix | hybrid-0.5 | none | 0.804 | 0.875 | 0.768 | 0.273 | 0.719 | 2092.531 | 0.914 | 46.764 |
| provision-contextual | bge-small-en-v1.5 | hybrid-0.5 | none | 0.801 | 0.938 | 0.829 | 0.250 | 0.688 | 2215.344 | 0.953 | 29.836 |
| provision-contextual | nomic+prefix | hybrid-0.5 | none | 0.799 | 0.969 | 0.835 | 0.258 | 0.656 | 2185.344 | 0.922 | 46.679 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | hybrid-0.5 | none | 0.797 | 0.844 | 0.791 | 0.219 | 0.719 | 3056.875 | 0.914 | 29.582 |
| structure | nomic+prefix | rrf(dense+bm25) | none | 0.794 | 0.875 | 0.801 | 0.234 | 0.688 | 1871.688 | 0.859 | 49.405 |
| structure | nomic (baseline) | rrf(dense+bm25) | none | 0.793 | 0.859 | 0.794 | 0.227 | 0.688 | 1836.406 | 0.777 | 38.175 |
| provision-contextual | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.788 | 0.828 | 0.780 | 0.219 | 0.719 | 2213.312 | 0.918 | 31.161 |
| provision-contextual | nomic (baseline) | hybrid-0.5 | none | 0.786 | 0.938 | 0.817 | 0.250 | 0.656 | 2181.844 | 0.945 | 37.067 |
| fixed-500/100 | nomic+prefix | hybrid-0.5 | none | 0.782 | 0.844 | 0.743 | 0.250 | 0.688 | 1593.438 | 0.891 | 48.856 |
| structure | bge-small-en-v1.5 | hybrid-0.5 | none | 0.771 | 0.906 | 0.793 | 0.242 | 0.656 | 1893.500 | 0.953 | 29.825 |
| sentence-600 | bge-small-en-v1.5 | hybrid-0.5 | none | 0.771 | 0.859 | 0.750 | 0.258 | 0.688 | 2103.500 | 0.922 | 29.810 |
| fixed-500/100 | bge-small-en-v1.5 | hybrid-0.5 | none | 0.768 | 0.828 | 0.732 | 0.234 | 0.688 | 1489.094 | 0.961 | 30.075 |
| sentence-600 | nomic (baseline) | rrf(dense+bm25) | none | 0.766 | 0.797 | 0.714 | 0.242 | 0.688 | 2101.000 | 0.883 | 38.491 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.764 | 0.812 | 0.755 | 0.211 | 0.656 | 3109.656 | 0.883 | 30.708 |
| provision-contextual | nomic (baseline) | rrf(dense+bm25) | none | 0.763 | 0.828 | 0.763 | 0.219 | 0.656 | 2195.500 | 0.789 | 38.530 |
| provision-contextual | nomic+prefix | rrf(dense+bm25) | none | 0.763 | 0.859 | 0.774 | 0.227 | 0.656 | 2192.750 | 0.863 | 47.981 |
| structure | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.760 | 0.844 | 0.768 | 0.227 | 0.688 | 1904.719 | 0.957 | 31.024 |
| sentence-600 | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.759 | 0.797 | 0.706 | 0.234 | 0.688 | 2096.094 | 0.852 | 31.076 |
| fixed-500/100 | nomic+prefix | rrf(dense+bm25) | none | 0.758 | 0.797 | 0.720 | 0.234 | 0.688 | 1560.750 | 0.859 | 51.855 |
| fixed-500/100 | nomic (baseline) | rrf(dense+bm25) | none | 0.753 | 0.781 | 0.706 | 0.219 | 0.688 | 1498.781 | 0.793 | 39.325 |
| fixed-500/100 | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.749 | 0.781 | 0.706 | 0.219 | 0.688 | 1472.469 | 1.000 | 31.329 |
| sentence-600 | nomic+prefix | rrf(dense+bm25) | none | 0.747 | 0.812 | 0.714 | 0.250 | 0.656 | 2109.125 | 0.844 | 48.110 |
| fixed-500/100 | nomic (baseline) | hybrid-0.5 | none | 0.747 | 0.812 | 0.713 | 0.227 | 0.656 | 1516.875 | 0.930 | 37.781 |
| sentence-600 | - | bm25 | none | 0.711 | 0.750 | 0.670 | 0.211 | 0.656 | 2095.312 | 0.844 | 1.246 |
| structure | - | bm25 | none | 0.693 | 0.750 | 0.692 | 0.195 | 0.625 | 1891.781 | 0.828 | 1.142 |
| provision-contextual | - | bm25 | none | 0.693 | 0.781 | 0.703 | 0.203 | 0.625 | 2214.406 | 0.820 | 1.276 |
| fixed-1000/200 (baseline) | - | bm25 | none | 0.685 | 0.750 | 0.677 | 0.195 | 0.562 | 3034.000 | 0.844 | 1.114 |
| fixed-500/100 | - | bm25 | none | 0.679 | 0.719 | 0.656 | 0.203 | 0.625 | 1451.031 | 0.828 | 1.205 |

## Split: dev

| chunker | embedder | retrieval | rerank | mrr | recall@4 | ndcg@4 | precision@4 | hit@1 | context_chars@4 | auroc_answerable | latency_ms_mean |
|---|---|---|---|---|---|---|---|---|---|---|---|
| structure | nomic+prefix | dense | none | 0.984 | 0.984 | 0.976 | 0.266 | 0.969 | 1802.531 | 0.781 | 47.356 |
| sentence-600 | nomic+prefix | dense | none | 0.969 | 0.984 | 0.947 | 0.320 | 0.938 | 2026.281 | 0.758 | 46.749 |
| fixed-500/100 | nomic+prefix | dense | none | 0.964 | 0.984 | 0.942 | 0.289 | 0.938 | 1678.094 | 0.789 | 48.815 |
| structure | nomic (baseline) | dense | none | 0.958 | 0.969 | 0.957 | 0.258 | 0.938 | 1788.594 | 0.844 | 36.968 |
| provision-contextual | nomic+prefix | dense | bge-reranker-base@20 | 0.958 | 0.984 | 0.957 | 0.266 | 0.938 | 2246.125 | 0.938 | 1919.449 |
| provision-contextual | nomic+prefix | rrf(dense+bm25) | bge-reranker-base@20 | 0.958 | 1.000 | 0.969 | 0.273 | 0.938 | 2247.562 | 0.938 | 1762.722 |
| provision-contextual | bge-small-en-v1.5 | dense | bge-reranker-base@20 | 0.958 | 1.000 | 0.969 | 0.273 | 0.938 | 2256.406 | 0.938 | 2607.884 |
| provision-contextual | bge-small-en-v1.5 | rrf(dense+bm25) | bge-reranker-base@20 | 0.958 | 0.984 | 0.957 | 0.266 | 0.938 | 2241.750 | 0.938 | 2104.397 |
| structure | nomic+prefix | dense | bge-reranker-base@20 | 0.958 | 0.969 | 0.957 | 0.266 | 0.938 | 1966.281 | 0.867 | 2405.939 |
| structure | nomic+prefix | rrf(dense+bm25) | bge-reranker-base@20 | 0.958 | 0.969 | 0.957 | 0.266 | 0.938 | 1966.781 | 0.867 | 1912.339 |
| structure | bge-small-en-v1.5 | dense | bge-reranker-base@20 | 0.958 | 0.969 | 0.957 | 0.266 | 0.938 | 1973.312 | 0.867 | 1692.449 |
| structure | bge-small-en-v1.5 | rrf(dense+bm25) | bge-reranker-base@20 | 0.958 | 0.953 | 0.945 | 0.258 | 0.938 | 1979.469 | 0.867 | 2184.882 |
| fixed-1000/200 (baseline) | nomic+prefix | dense | bge-reranker-base@20 | 0.943 | 1.000 | 0.955 | 0.273 | 0.906 | 3089.844 | 0.852 | 1979.418 |
| fixed-1000/200 (baseline) | nomic+prefix | rrf(dense+bm25) | bge-reranker-base@20 | 0.943 | 1.000 | 0.955 | 0.273 | 0.906 | 3089.844 | 0.852 | 2278.491 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | dense | bge-reranker-base@20 | 0.943 | 1.000 | 0.955 | 0.273 | 0.906 | 3089.844 | 0.852 | 1588.225 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | rrf(dense+bm25) | bge-reranker-base@20 | 0.943 | 1.000 | 0.955 | 0.273 | 0.906 | 3089.844 | 0.852 | 1698.184 |
| provision-contextual | nomic (baseline) | dense | none | 0.940 | 0.969 | 0.946 | 0.258 | 0.906 | 2193.969 | 0.859 | 37.050 |
| structure | bge-small-en-v1.5 | dense | none | 0.940 | 0.969 | 0.946 | 0.258 | 0.906 | 1869.156 | 0.891 | 29.810 |
| provision-contextual | bge-small-en-v1.5 | dense | none | 0.940 | 0.969 | 0.946 | 0.258 | 0.906 | 2187.281 | 0.883 | 29.822 |
| fixed-500/100 | nomic (baseline) | dense | none | 0.937 | 0.969 | 0.927 | 0.281 | 0.906 | 1524.219 | 0.836 | 37.756 |
| sentence-600 | bge-small-en-v1.5 | dense | none | 0.936 | 0.969 | 0.908 | 0.297 | 0.906 | 2061.844 | 0.836 | 29.796 |
| fixed-500/100 | bge-small-en-v1.5 | dense | none | 0.928 | 0.938 | 0.898 | 0.266 | 0.906 | 1511.844 | 0.859 | 30.055 |
| provision-contextual | nomic+prefix | dense | none | 0.927 | 0.969 | 0.934 | 0.258 | 0.875 | 2172.656 | 0.758 | 46.665 |
| fixed-1000/200 (baseline) | nomic (baseline) | dense | none | 0.917 | 0.984 | 0.928 | 0.266 | 0.844 | 2976.594 | 0.648 | 36.572 |
| sentence-600 | nomic (baseline) | dense | none | 0.910 | 0.969 | 0.904 | 0.312 | 0.844 | 2052.688 | 0.805 | 37.049 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | dense | none | 0.909 | 0.969 | 0.920 | 0.258 | 0.844 | 3123.250 | 0.703 | 29.572 |
| fixed-1000/200 (baseline) | nomic (baseline) | hybrid-0.5 | none | 0.901 | 0.984 | 0.918 | 0.266 | 0.812 | 2987.531 | 0.711 | 36.583 |
| structure | nomic+prefix | hybrid-0.5 | none | 0.891 | 0.922 | 0.887 | 0.250 | 0.844 | 1814.938 | 0.812 | 47.383 |
| provision-contextual | nomic (baseline) | hybrid-0.5 | none | 0.888 | 0.906 | 0.883 | 0.242 | 0.844 | 2162.719 | 0.891 | 37.067 |
| fixed-1000/200 (baseline) | nomic+prefix | dense | none | 0.885 | 0.922 | 0.879 | 0.242 | 0.812 | 3009.906 | 0.594 | 47.340 |
| fixed-500/100 | nomic+prefix | hybrid-0.5 | none | 0.882 | 0.922 | 0.863 | 0.273 | 0.844 | 1649.562 | 0.734 | 48.856 |
| sentence-600 | nomic (baseline) | hybrid-0.5 | none | 0.878 | 0.906 | 0.864 | 0.305 | 0.844 | 2077.062 | 0.836 | 37.067 |
| structure | nomic (baseline) | hybrid-0.5 | none | 0.870 | 0.906 | 0.872 | 0.242 | 0.812 | 1819.906 | 0.859 | 36.983 |
| provision-contextual | nomic+prefix | hybrid-0.5 | none | 0.868 | 0.906 | 0.868 | 0.242 | 0.812 | 2176.156 | 0.812 | 46.679 |
| fixed-500/100 | nomic (baseline) | rrf(dense+bm25) | none | 0.866 | 0.875 | 0.842 | 0.258 | 0.844 | 1660.094 | 0.551 | 39.325 |
| fixed-500/100 | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.865 | 0.875 | 0.833 | 0.250 | 0.844 | 1630.000 | 0.578 | 31.329 |
| provision-contextual | nomic (baseline) | rrf(dense+bm25) | none | 0.864 | 0.844 | 0.841 | 0.227 | 0.844 | 2193.438 | 0.566 | 38.530 |
| fixed-1000/200 (baseline) | nomic (baseline) | rrf(dense+bm25) | none | 0.864 | 0.938 | 0.873 | 0.250 | 0.781 | 2943.250 | 0.551 | 37.822 |
| provision-contextual | nomic+prefix | rrf(dense+bm25) | none | 0.864 | 0.844 | 0.841 | 0.227 | 0.844 | 2215.781 | 0.457 | 47.981 |
| provision-contextual | bge-small-en-v1.5 | hybrid-0.5 | none | 0.863 | 0.906 | 0.865 | 0.242 | 0.812 | 2150.969 | 0.906 | 29.836 |
| fixed-500/100 | nomic (baseline) | hybrid-0.5 | none | 0.862 | 0.906 | 0.855 | 0.266 | 0.812 | 1640.250 | 0.867 | 37.781 |
| structure | bge-small-en-v1.5 | hybrid-0.5 | none | 0.862 | 0.906 | 0.868 | 0.242 | 0.812 | 1833.469 | 0.906 | 29.825 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | hybrid-0.5 | none | 0.860 | 0.938 | 0.871 | 0.250 | 0.781 | 3036.844 | 0.805 | 29.582 |
| fixed-500/100 | nomic+prefix | rrf(dense+bm25) | none | 0.859 | 0.875 | 0.835 | 0.258 | 0.812 | 1663.969 | 0.457 | 51.855 |
| fixed-1000/200 (baseline) | nomic+prefix | hybrid-0.5 | none | 0.855 | 0.969 | 0.879 | 0.258 | 0.750 | 2985.969 | 0.727 | 47.373 |
| sentence-600 | nomic+prefix | hybrid-0.5 | none | 0.855 | 0.922 | 0.840 | 0.305 | 0.781 | 2080.250 | 0.828 | 46.764 |
| structure | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.854 | 0.875 | 0.845 | 0.234 | 0.812 | 1880.562 | 0.469 | 31.024 |
| sentence-600 | nomic (baseline) | rrf(dense+bm25) | none | 0.852 | 0.906 | 0.837 | 0.297 | 0.812 | 2080.000 | 0.535 | 38.491 |
| structure | nomic+prefix | rrf(dense+bm25) | none | 0.852 | 0.875 | 0.843 | 0.234 | 0.812 | 1856.500 | 0.480 | 49.405 |
| sentence-600 | nomic+prefix | rrf(dense+bm25) | none | 0.851 | 0.906 | 0.838 | 0.297 | 0.812 | 2069.531 | 0.535 | 48.110 |
| fixed-500/100 | bge-small-en-v1.5 | hybrid-0.5 | none | 0.850 | 0.875 | 0.826 | 0.250 | 0.812 | 1624.375 | 0.875 | 30.075 |
| structure | nomic (baseline) | rrf(dense+bm25) | none | 0.850 | 0.875 | 0.843 | 0.234 | 0.812 | 1856.312 | 0.586 | 38.175 |
| fixed-1000/200 (baseline) | nomic+prefix | rrf(dense+bm25) | none | 0.847 | 0.938 | 0.860 | 0.250 | 0.750 | 3008.156 | 0.578 | 51.485 |
| sentence-600 | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.842 | 0.875 | 0.806 | 0.281 | 0.781 | 2084.188 | 0.570 | 31.076 |
| sentence-600 | bge-small-en-v1.5 | hybrid-0.5 | none | 0.839 | 0.906 | 0.808 | 0.281 | 0.781 | 2074.656 | 0.891 | 29.810 |
| provision-contextual | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.834 | 0.875 | 0.832 | 0.234 | 0.781 | 2211.969 | 0.605 | 31.161 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.833 | 0.906 | 0.840 | 0.242 | 0.750 | 3048.281 | 0.590 | 30.708 |
| fixed-1000/200 (baseline) | - | bm25 | none | 0.769 | 0.875 | 0.784 | 0.234 | 0.656 | 2954.438 | 0.766 | 1.114 |
| fixed-500/100 | - | bm25 | none | 0.742 | 0.812 | 0.721 | 0.227 | 0.656 | 1597.438 | 0.750 | 1.205 |
| structure | - | bm25 | none | 0.738 | 0.844 | 0.755 | 0.227 | 0.656 | 1828.531 | 0.797 | 1.142 |
| provision-contextual | - | bm25 | none | 0.737 | 0.812 | 0.742 | 0.219 | 0.656 | 2159.375 | 0.727 | 1.276 |
| sentence-600 | - | bm25 | none | 0.735 | 0.812 | 0.702 | 0.258 | 0.656 | 2087.844 | 0.812 | 1.246 |

## Split: all

| chunker | embedder | retrieval | rerank | mrr | recall@4 | ndcg@4 | precision@4 | hit@1 | context_chars@4 | auroc_answerable | latency_ms_mean |
|---|---|---|---|---|---|---|---|---|---|---|---|
| structure | nomic+prefix | dense | none | 0.928 | 0.977 | 0.931 | 0.262 | 0.875 | 1840.531 | 0.826 | 47.356 |
| structure | bge-small-en-v1.5 | rrf(dense+bm25) | bge-reranker-base@20 | 0.927 | 0.945 | 0.924 | 0.250 | 0.891 | 1975.750 | 0.910 | 2184.882 |
| structure | nomic+prefix | rrf(dense+bm25) | bge-reranker-base@20 | 0.927 | 0.953 | 0.930 | 0.254 | 0.891 | 1973.000 | 0.910 | 1912.339 |
| structure | nomic+prefix | dense | bge-reranker-base@20 | 0.927 | 0.953 | 0.930 | 0.254 | 0.891 | 1959.250 | 0.910 | 2405.939 |
| structure | bge-small-en-v1.5 | dense | bge-reranker-base@20 | 0.927 | 0.953 | 0.930 | 0.254 | 0.891 | 1966.219 | 0.910 | 1692.449 |
| fixed-500/100 | nomic+prefix | dense | none | 0.917 | 0.945 | 0.894 | 0.285 | 0.875 | 1621.969 | 0.848 | 48.815 |
| provision-contextual | nomic+prefix | dense | bge-reranker-base@20 | 0.915 | 0.961 | 0.920 | 0.254 | 0.875 | 2244.484 | 0.941 | 1919.449 |
| provision-contextual | nomic+prefix | rrf(dense+bm25) | bge-reranker-base@20 | 0.915 | 0.969 | 0.926 | 0.258 | 0.875 | 2244.719 | 0.941 | 1762.722 |
| provision-contextual | bge-small-en-v1.5 | rrf(dense+bm25) | bge-reranker-base@20 | 0.915 | 0.961 | 0.920 | 0.254 | 0.875 | 2234.750 | 0.941 | 2104.397 |
| provision-contextual | bge-small-en-v1.5 | dense | bge-reranker-base@20 | 0.915 | 0.969 | 0.926 | 0.258 | 0.875 | 2241.688 | 0.941 | 2607.884 |
| sentence-600 | nomic+prefix | dense | none | 0.910 | 0.945 | 0.886 | 0.309 | 0.859 | 2046.203 | 0.816 | 46.749 |
| structure | nomic (baseline) | dense | none | 0.908 | 0.969 | 0.919 | 0.258 | 0.844 | 1805.031 | 0.850 | 36.968 |
| structure | bge-small-en-v1.5 | dense | none | 0.897 | 0.953 | 0.909 | 0.254 | 0.844 | 1884.156 | 0.910 | 29.810 |
| fixed-1000/200 (baseline) | nomic+prefix | dense | bge-reranker-base@20 | 0.896 | 0.953 | 0.905 | 0.254 | 0.844 | 3079.297 | 0.906 | 1979.418 |
| fixed-1000/200 (baseline) | nomic+prefix | rrf(dense+bm25) | bge-reranker-base@20 | 0.896 | 0.953 | 0.905 | 0.254 | 0.844 | 3079.297 | 0.906 | 2278.491 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | dense | bge-reranker-base@20 | 0.896 | 0.953 | 0.905 | 0.254 | 0.844 | 3079.297 | 0.906 | 1588.225 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | rrf(dense+bm25) | bge-reranker-base@20 | 0.896 | 0.953 | 0.905 | 0.254 | 0.844 | 3079.297 | 0.906 | 1698.184 |
| provision-contextual | bge-small-en-v1.5 | dense | none | 0.894 | 0.953 | 0.906 | 0.254 | 0.828 | 2206.438 | 0.902 | 29.822 |
| sentence-600 | bge-small-en-v1.5 | dense | none | 0.889 | 0.930 | 0.870 | 0.297 | 0.844 | 2071.266 | 0.879 | 29.796 |
| provision-contextual | nomic (baseline) | dense | none | 0.887 | 0.969 | 0.905 | 0.258 | 0.812 | 2208.094 | 0.857 | 37.050 |
| fixed-500/100 | bge-small-en-v1.5 | dense | none | 0.883 | 0.914 | 0.860 | 0.266 | 0.844 | 1448.156 | 0.900 | 30.055 |
| sentence-600 | nomic (baseline) | dense | none | 0.881 | 0.938 | 0.860 | 0.301 | 0.797 | 2062.219 | 0.844 | 37.049 |
| fixed-500/100 | nomic (baseline) | dense | none | 0.879 | 0.922 | 0.860 | 0.266 | 0.828 | 1522.109 | 0.855 | 37.756 |
| provision-contextual | nomic+prefix | dense | none | 0.878 | 0.969 | 0.896 | 0.258 | 0.781 | 2171.422 | 0.799 | 46.665 |
| fixed-1000/200 (baseline) | nomic (baseline) | hybrid-0.5 | none | 0.873 | 0.953 | 0.885 | 0.254 | 0.781 | 3011.781 | 0.799 | 36.583 |
| fixed-1000/200 (baseline) | nomic (baseline) | dense | none | 0.867 | 0.953 | 0.881 | 0.254 | 0.766 | 2990.656 | 0.758 | 36.572 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | dense | none | 0.863 | 0.906 | 0.863 | 0.238 | 0.797 | 3103.156 | 0.805 | 29.572 |
| structure | nomic+prefix | hybrid-0.5 | none | 0.858 | 0.930 | 0.861 | 0.250 | 0.781 | 1826.281 | 0.844 | 47.383 |
| fixed-1000/200 (baseline) | nomic+prefix | dense | none | 0.857 | 0.922 | 0.861 | 0.242 | 0.766 | 3035.766 | 0.727 | 47.340 |
| fixed-1000/200 (baseline) | nomic (baseline) | rrf(dense+bm25) | none | 0.846 | 0.914 | 0.851 | 0.242 | 0.750 | 2990.719 | 0.734 | 37.822 |
| sentence-600 | nomic (baseline) | hybrid-0.5 | none | 0.845 | 0.891 | 0.820 | 0.289 | 0.781 | 2082.547 | 0.857 | 37.067 |
| fixed-1000/200 (baseline) | nomic+prefix | hybrid-0.5 | none | 0.844 | 0.945 | 0.863 | 0.250 | 0.750 | 3007.547 | 0.785 | 47.373 |
| fixed-1000/200 (baseline) | nomic+prefix | rrf(dense+bm25) | none | 0.839 | 0.922 | 0.850 | 0.246 | 0.750 | 3016.859 | 0.719 | 51.485 |
| structure | nomic (baseline) | hybrid-0.5 | none | 0.838 | 0.922 | 0.852 | 0.246 | 0.750 | 1830.328 | 0.867 | 36.983 |
| provision-contextual | nomic (baseline) | hybrid-0.5 | none | 0.837 | 0.922 | 0.850 | 0.246 | 0.750 | 2172.281 | 0.891 | 37.067 |
| provision-contextual | nomic+prefix | hybrid-0.5 | none | 0.834 | 0.938 | 0.851 | 0.250 | 0.734 | 2180.750 | 0.848 | 46.679 |
| fixed-500/100 | nomic+prefix | hybrid-0.5 | none | 0.832 | 0.883 | 0.803 | 0.262 | 0.766 | 1621.500 | 0.812 | 48.856 |
| provision-contextual | bge-small-en-v1.5 | hybrid-0.5 | none | 0.832 | 0.922 | 0.847 | 0.246 | 0.750 | 2183.156 | 0.918 | 29.836 |
| sentence-600 | nomic+prefix | hybrid-0.5 | none | 0.829 | 0.898 | 0.804 | 0.289 | 0.750 | 2086.391 | 0.857 | 46.764 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | hybrid-0.5 | none | 0.829 | 0.891 | 0.831 | 0.234 | 0.750 | 3046.859 | 0.844 | 29.582 |
| structure | nomic+prefix | rrf(dense+bm25) | none | 0.823 | 0.875 | 0.822 | 0.234 | 0.750 | 1864.094 | 0.663 | 49.405 |
| structure | nomic (baseline) | rrf(dense+bm25) | none | 0.821 | 0.867 | 0.819 | 0.230 | 0.750 | 1846.359 | 0.670 | 38.175 |
| structure | bge-small-en-v1.5 | hybrid-0.5 | none | 0.817 | 0.906 | 0.830 | 0.242 | 0.734 | 1863.484 | 0.900 | 29.825 |
| provision-contextual | nomic (baseline) | rrf(dense+bm25) | none | 0.814 | 0.836 | 0.802 | 0.223 | 0.750 | 2194.469 | 0.670 | 38.530 |
| provision-contextual | nomic+prefix | rrf(dense+bm25) | none | 0.813 | 0.852 | 0.808 | 0.227 | 0.750 | 2204.266 | 0.660 | 47.981 |
| provision-contextual | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.811 | 0.852 | 0.806 | 0.227 | 0.750 | 2212.641 | 0.756 | 31.161 |
| sentence-600 | nomic (baseline) | rrf(dense+bm25) | none | 0.809 | 0.852 | 0.775 | 0.270 | 0.750 | 2090.500 | 0.703 | 38.491 |
| fixed-500/100 | nomic (baseline) | rrf(dense+bm25) | none | 0.809 | 0.828 | 0.774 | 0.238 | 0.766 | 1579.438 | 0.667 | 39.325 |
| fixed-500/100 | bge-small-en-v1.5 | hybrid-0.5 | none | 0.809 | 0.852 | 0.779 | 0.242 | 0.750 | 1556.734 | 0.891 | 30.075 |
| fixed-500/100 | nomic+prefix | rrf(dense+bm25) | none | 0.809 | 0.836 | 0.778 | 0.246 | 0.750 | 1612.359 | 0.656 | 51.855 |
| structure | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.807 | 0.859 | 0.806 | 0.230 | 0.750 | 1892.641 | 0.712 | 31.024 |
| fixed-500/100 | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.807 | 0.828 | 0.769 | 0.234 | 0.766 | 1551.234 | 0.778 | 31.329 |
| sentence-600 | bge-small-en-v1.5 | hybrid-0.5 | none | 0.805 | 0.883 | 0.779 | 0.270 | 0.734 | 2089.078 | 0.889 | 29.810 |
| fixed-500/100 | nomic (baseline) | hybrid-0.5 | none | 0.805 | 0.859 | 0.784 | 0.246 | 0.734 | 1578.562 | 0.881 | 37.781 |
| sentence-600 | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.801 | 0.836 | 0.756 | 0.258 | 0.734 | 2090.141 | 0.714 | 31.076 |
| sentence-600 | nomic+prefix | rrf(dense+bm25) | none | 0.799 | 0.859 | 0.776 | 0.273 | 0.734 | 2089.328 | 0.681 | 48.110 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.799 | 0.859 | 0.797 | 0.227 | 0.703 | 3078.969 | 0.746 | 30.708 |
| fixed-1000/200 (baseline) | - | bm25 | none | 0.727 | 0.812 | 0.730 | 0.215 | 0.609 | 2994.219 | 0.814 | 1.114 |
| sentence-600 | - | bm25 | none | 0.723 | 0.781 | 0.686 | 0.234 | 0.656 | 2091.578 | 0.828 | 1.246 |
| structure | - | bm25 | none | 0.716 | 0.797 | 0.724 | 0.211 | 0.641 | 1860.156 | 0.809 | 1.142 |
| provision-contextual | - | bm25 | none | 0.715 | 0.797 | 0.722 | 0.211 | 0.641 | 2186.891 | 0.779 | 1.276 |
| fixed-500/100 | - | bm25 | none | 0.711 | 0.766 | 0.689 | 0.215 | 0.641 | 1524.234 | 0.791 | 1.205 |

## As-deployed baseline (server flow with relevance gate)

| split | recall (chunks passed) | false refusal | correct refusal | mean chunks passed |
|---|---|---|---|---|
| dev | 0.969 | 0.031 | 0.250 | 3.56 |
| test | 0.812 | 0.156 | 0.750 | 2.84 |
| all | 0.891 | 0.094 | 0.500 | 3.20 |
