## Split: test

| chunker | embedder | retrieval | rerank | mrr | recall@4 | ndcg@4 | precision@4 | hit@1 | context_chars@4 | auroc_answerable | latency_ms_mean |
|---|---|---|---|---|---|---|---|---|---|---|---|
| structure | nomic+prefix | dense | none | 0.872 | 0.969 | 0.885 | 0.258 | 0.781 | 1878.531 | 0.898 | 32.347 |
| fixed-500/100 | nomic+prefix | dense | none | 0.870 | 0.906 | 0.846 | 0.281 | 0.812 | 1565.844 | 0.906 | 32.842 |
| structure | nomic (baseline) | dense | none | 0.857 | 0.969 | 0.880 | 0.258 | 0.750 | 1821.469 | 0.898 | 68.439 |
| structure | bge-small-en-v1.5 | dense | none | 0.855 | 0.938 | 0.872 | 0.250 | 0.781 | 1899.156 | 0.938 | 27.652 |
| sentence-600 | nomic (baseline) | dense | none | 0.851 | 0.906 | 0.817 | 0.289 | 0.750 | 2071.750 | 0.914 | 68.824 |
| sentence-600 | nomic+prefix | dense | none | 0.851 | 0.906 | 0.825 | 0.297 | 0.781 | 2066.125 | 0.883 | 32.351 |
| provision-contextual | bge-small-en-v1.5 | dense | none | 0.848 | 0.938 | 0.866 | 0.250 | 0.750 | 2225.594 | 0.945 | 27.654 |
| fixed-1000/200 (baseline) | nomic (baseline) | hybrid-0.5 | none | 0.845 | 0.922 | 0.852 | 0.242 | 0.750 | 3036.031 | 0.938 | 68.765 |
| sentence-600 | bge-small-en-v1.5 | dense | none | 0.843 | 0.891 | 0.832 | 0.297 | 0.781 | 2080.688 | 0.930 | 27.651 |
| fixed-500/100 | bge-small-en-v1.5 | dense | none | 0.837 | 0.891 | 0.822 | 0.266 | 0.781 | 1384.469 | 0.930 | 27.906 |
| fixed-1000/200 (baseline) | nomic+prefix | hybrid-0.5 | none | 0.833 | 0.922 | 0.846 | 0.242 | 0.750 | 3029.125 | 0.883 | 31.950 |
| provision-contextual | nomic (baseline) | dense | none | 0.833 | 0.969 | 0.864 | 0.258 | 0.719 | 2222.219 | 0.875 | 68.390 |
| fixed-1000/200 (baseline) | nomic+prefix | rrf(dense+bm25) | none | 0.831 | 0.906 | 0.840 | 0.242 | 0.750 | 3025.562 | 0.867 | 33.115 |
| fixed-1000/200 (baseline) | nomic+prefix | dense | none | 0.829 | 0.922 | 0.843 | 0.242 | 0.719 | 3061.625 | 0.844 | 31.940 |
| provision-contextual | nomic+prefix | dense | none | 0.828 | 0.969 | 0.857 | 0.258 | 0.688 | 2170.188 | 0.867 | 32.353 |
| fixed-1000/200 (baseline) | nomic (baseline) | rrf(dense+bm25) | none | 0.827 | 0.891 | 0.829 | 0.234 | 0.719 | 3038.188 | 0.914 | 71.111 |
| structure | nomic+prefix | hybrid-0.5 | none | 0.824 | 0.938 | 0.836 | 0.250 | 0.719 | 1837.625 | 0.914 | 32.361 |
| fixed-500/100 | nomic (baseline) | dense | none | 0.821 | 0.875 | 0.792 | 0.250 | 0.750 | 1520.000 | 0.898 | 71.519 |
| fixed-1000/200 (baseline) | nomic (baseline) | dense | none | 0.818 | 0.922 | 0.834 | 0.242 | 0.688 | 3004.719 | 0.867 | 68.738 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | dense | none | 0.816 | 0.844 | 0.805 | 0.219 | 0.750 | 3083.062 | 0.906 | 27.437 |
| sentence-600 | nomic (baseline) | hybrid-0.5 | none | 0.812 | 0.875 | 0.776 | 0.273 | 0.719 | 2088.031 | 0.953 | 68.844 |
| structure | nomic (baseline) | hybrid-0.5 | none | 0.807 | 0.938 | 0.831 | 0.250 | 0.688 | 1840.750 | 0.930 | 68.455 |
| sentence-600 | nomic+prefix | hybrid-0.5 | none | 0.804 | 0.875 | 0.768 | 0.273 | 0.719 | 2092.531 | 0.914 | 32.366 |
| provision-contextual | bge-small-en-v1.5 | hybrid-0.5 | none | 0.801 | 0.938 | 0.829 | 0.250 | 0.688 | 2215.344 | 0.953 | 27.668 |
| provision-contextual | nomic+prefix | hybrid-0.5 | none | 0.799 | 0.969 | 0.835 | 0.258 | 0.656 | 2185.344 | 0.922 | 32.367 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | hybrid-0.5 | none | 0.797 | 0.844 | 0.791 | 0.219 | 0.719 | 3056.875 | 0.914 | 27.448 |
| structure | nomic+prefix | rrf(dense+bm25) | none | 0.794 | 0.875 | 0.801 | 0.234 | 0.688 | 1871.688 | 0.859 | 33.515 |
| structure | nomic (baseline) | rrf(dense+bm25) | none | 0.793 | 0.859 | 0.794 | 0.227 | 0.688 | 1836.406 | 0.777 | 69.718 |
| provision-contextual | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.788 | 0.828 | 0.780 | 0.219 | 0.719 | 2213.312 | 0.918 | 28.968 |
| provision-contextual | nomic (baseline) | hybrid-0.5 | none | 0.786 | 0.938 | 0.817 | 0.250 | 0.656 | 2181.844 | 0.945 | 68.403 |
| fixed-500/100 | nomic+prefix | hybrid-0.5 | none | 0.782 | 0.844 | 0.743 | 0.250 | 0.688 | 1593.438 | 0.891 | 32.861 |
| structure | bge-small-en-v1.5 | hybrid-0.5 | none | 0.771 | 0.906 | 0.793 | 0.242 | 0.656 | 1893.500 | 0.953 | 27.666 |
| sentence-600 | bge-small-en-v1.5 | hybrid-0.5 | none | 0.771 | 0.859 | 0.750 | 0.258 | 0.688 | 2103.500 | 0.922 | 27.665 |
| fixed-500/100 | bge-small-en-v1.5 | hybrid-0.5 | none | 0.768 | 0.828 | 0.732 | 0.234 | 0.688 | 1489.094 | 0.961 | 27.925 |
| sentence-600 | nomic (baseline) | rrf(dense+bm25) | none | 0.766 | 0.797 | 0.714 | 0.242 | 0.688 | 2101.000 | 0.883 | 70.597 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.764 | 0.812 | 0.755 | 0.211 | 0.656 | 3109.656 | 0.883 | 28.591 |
| provision-contextual | nomic (baseline) | rrf(dense+bm25) | none | 0.763 | 0.828 | 0.763 | 0.219 | 0.656 | 2195.500 | 0.789 | 69.697 |
| provision-contextual | nomic+prefix | rrf(dense+bm25) | none | 0.763 | 0.859 | 0.774 | 0.227 | 0.656 | 2192.750 | 0.863 | 33.662 |
| structure | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.760 | 0.844 | 0.768 | 0.227 | 0.688 | 1904.719 | 0.957 | 28.813 |
| sentence-600 | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.759 | 0.797 | 0.706 | 0.234 | 0.688 | 2096.094 | 0.852 | 28.925 |
| fixed-500/100 | nomic+prefix | rrf(dense+bm25) | none | 0.758 | 0.797 | 0.720 | 0.234 | 0.688 | 1560.750 | 0.859 | 34.086 |
| fixed-500/100 | nomic (baseline) | rrf(dense+bm25) | none | 0.753 | 0.781 | 0.706 | 0.219 | 0.688 | 1498.781 | 0.793 | 74.422 |
| fixed-500/100 | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.749 | 0.781 | 0.706 | 0.219 | 0.688 | 1472.469 | 1.000 | 29.152 |
| sentence-600 | nomic+prefix | rrf(dense+bm25) | none | 0.747 | 0.812 | 0.714 | 0.250 | 0.656 | 2109.125 | 0.844 | 33.664 |
| fixed-500/100 | nomic (baseline) | hybrid-0.5 | none | 0.747 | 0.812 | 0.713 | 0.227 | 0.656 | 1516.875 | 0.930 | 71.569 |
| sentence-600 | - | bm25 | none | 0.711 | 0.750 | 0.670 | 0.211 | 0.656 | 2095.312 | 0.844 | 1.270 |
| structure | - | bm25 | none | 0.693 | 0.750 | 0.692 | 0.195 | 0.625 | 1891.781 | 0.828 | 1.160 |
| provision-contextual | - | bm25 | none | 0.693 | 0.781 | 0.703 | 0.203 | 0.625 | 2214.406 | 0.820 | 1.352 |
| fixed-1000/200 (baseline) | - | bm25 | none | 0.685 | 0.750 | 0.677 | 0.195 | 0.562 | 3034.000 | 0.844 | 1.174 |
| fixed-500/100 | - | bm25 | none | 0.679 | 0.719 | 0.656 | 0.203 | 0.625 | 1451.031 | 0.828 | 1.706 |

## Split: dev

| chunker | embedder | retrieval | rerank | mrr | recall@4 | ndcg@4 | precision@4 | hit@1 | context_chars@4 | auroc_answerable | latency_ms_mean |
|---|---|---|---|---|---|---|---|---|---|---|---|
| structure | nomic+prefix | dense | none | 0.984 | 0.984 | 0.976 | 0.266 | 0.969 | 1802.531 | 0.781 | 32.347 |
| sentence-600 | nomic+prefix | dense | none | 0.969 | 0.984 | 0.947 | 0.320 | 0.938 | 2026.281 | 0.758 | 32.351 |
| fixed-500/100 | nomic+prefix | dense | none | 0.964 | 0.984 | 0.942 | 0.289 | 0.938 | 1678.094 | 0.789 | 32.842 |
| structure | nomic (baseline) | dense | none | 0.958 | 0.969 | 0.957 | 0.258 | 0.938 | 1788.594 | 0.844 | 68.439 |
| provision-contextual | nomic (baseline) | dense | none | 0.940 | 0.969 | 0.946 | 0.258 | 0.906 | 2193.969 | 0.859 | 68.390 |
| structure | bge-small-en-v1.5 | dense | none | 0.940 | 0.969 | 0.946 | 0.258 | 0.906 | 1869.156 | 0.891 | 27.652 |
| provision-contextual | bge-small-en-v1.5 | dense | none | 0.940 | 0.969 | 0.946 | 0.258 | 0.906 | 2187.281 | 0.883 | 27.654 |
| fixed-500/100 | nomic (baseline) | dense | none | 0.937 | 0.969 | 0.927 | 0.281 | 0.906 | 1524.219 | 0.836 | 71.519 |
| sentence-600 | bge-small-en-v1.5 | dense | none | 0.936 | 0.969 | 0.908 | 0.297 | 0.906 | 2061.844 | 0.836 | 27.651 |
| fixed-500/100 | bge-small-en-v1.5 | dense | none | 0.928 | 0.938 | 0.898 | 0.266 | 0.906 | 1511.844 | 0.859 | 27.906 |
| provision-contextual | nomic+prefix | dense | none | 0.927 | 0.969 | 0.934 | 0.258 | 0.875 | 2172.656 | 0.758 | 32.353 |
| fixed-1000/200 (baseline) | nomic (baseline) | dense | none | 0.917 | 0.984 | 0.928 | 0.266 | 0.844 | 2976.594 | 0.648 | 68.738 |
| sentence-600 | nomic (baseline) | dense | none | 0.910 | 0.969 | 0.904 | 0.312 | 0.844 | 2052.688 | 0.805 | 68.824 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | dense | none | 0.909 | 0.969 | 0.920 | 0.258 | 0.844 | 3123.250 | 0.703 | 27.437 |
| fixed-1000/200 (baseline) | nomic (baseline) | hybrid-0.5 | none | 0.901 | 0.984 | 0.918 | 0.266 | 0.812 | 2987.531 | 0.711 | 68.765 |
| structure | nomic+prefix | hybrid-0.5 | none | 0.891 | 0.922 | 0.887 | 0.250 | 0.844 | 1814.938 | 0.812 | 32.361 |
| provision-contextual | nomic (baseline) | hybrid-0.5 | none | 0.888 | 0.906 | 0.883 | 0.242 | 0.844 | 2162.719 | 0.891 | 68.403 |
| fixed-1000/200 (baseline) | nomic+prefix | dense | none | 0.885 | 0.922 | 0.879 | 0.242 | 0.812 | 3009.906 | 0.594 | 31.940 |
| fixed-500/100 | nomic+prefix | hybrid-0.5 | none | 0.882 | 0.922 | 0.863 | 0.273 | 0.844 | 1649.562 | 0.734 | 32.861 |
| sentence-600 | nomic (baseline) | hybrid-0.5 | none | 0.878 | 0.906 | 0.864 | 0.305 | 0.844 | 2077.062 | 0.836 | 68.844 |
| structure | nomic (baseline) | hybrid-0.5 | none | 0.870 | 0.906 | 0.872 | 0.242 | 0.812 | 1819.906 | 0.859 | 68.455 |
| provision-contextual | nomic+prefix | hybrid-0.5 | none | 0.868 | 0.906 | 0.868 | 0.242 | 0.812 | 2176.156 | 0.812 | 32.367 |
| fixed-500/100 | nomic (baseline) | rrf(dense+bm25) | none | 0.866 | 0.875 | 0.842 | 0.258 | 0.844 | 1660.094 | 0.551 | 74.422 |
| fixed-500/100 | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.865 | 0.875 | 0.833 | 0.250 | 0.844 | 1630.000 | 0.578 | 29.152 |
| provision-contextual | nomic (baseline) | rrf(dense+bm25) | none | 0.864 | 0.844 | 0.841 | 0.227 | 0.844 | 2193.438 | 0.566 | 69.697 |
| fixed-1000/200 (baseline) | nomic (baseline) | rrf(dense+bm25) | none | 0.864 | 0.938 | 0.873 | 0.250 | 0.781 | 2943.250 | 0.551 | 71.111 |
| provision-contextual | nomic+prefix | rrf(dense+bm25) | none | 0.864 | 0.844 | 0.841 | 0.227 | 0.844 | 2215.781 | 0.457 | 33.662 |
| provision-contextual | bge-small-en-v1.5 | hybrid-0.5 | none | 0.863 | 0.906 | 0.865 | 0.242 | 0.812 | 2150.969 | 0.906 | 27.668 |
| fixed-500/100 | nomic (baseline) | hybrid-0.5 | none | 0.862 | 0.906 | 0.855 | 0.266 | 0.812 | 1640.250 | 0.867 | 71.569 |
| structure | bge-small-en-v1.5 | hybrid-0.5 | none | 0.862 | 0.906 | 0.868 | 0.242 | 0.812 | 1833.469 | 0.906 | 27.666 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | hybrid-0.5 | none | 0.860 | 0.938 | 0.871 | 0.250 | 0.781 | 3036.844 | 0.805 | 27.448 |
| fixed-500/100 | nomic+prefix | rrf(dense+bm25) | none | 0.859 | 0.875 | 0.835 | 0.258 | 0.812 | 1663.969 | 0.457 | 34.086 |
| fixed-1000/200 (baseline) | nomic+prefix | hybrid-0.5 | none | 0.855 | 0.969 | 0.879 | 0.258 | 0.750 | 2985.969 | 0.727 | 31.950 |
| sentence-600 | nomic+prefix | hybrid-0.5 | none | 0.855 | 0.922 | 0.840 | 0.305 | 0.781 | 2080.250 | 0.828 | 32.366 |
| structure | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.854 | 0.875 | 0.845 | 0.234 | 0.812 | 1880.562 | 0.469 | 28.813 |
| sentence-600 | nomic (baseline) | rrf(dense+bm25) | none | 0.852 | 0.906 | 0.837 | 0.297 | 0.812 | 2080.000 | 0.535 | 70.597 |
| structure | nomic+prefix | rrf(dense+bm25) | none | 0.852 | 0.875 | 0.843 | 0.234 | 0.812 | 1856.500 | 0.480 | 33.515 |
| sentence-600 | nomic+prefix | rrf(dense+bm25) | none | 0.851 | 0.906 | 0.838 | 0.297 | 0.812 | 2069.531 | 0.535 | 33.664 |
| fixed-500/100 | bge-small-en-v1.5 | hybrid-0.5 | none | 0.850 | 0.875 | 0.826 | 0.250 | 0.812 | 1624.375 | 0.875 | 27.925 |
| structure | nomic (baseline) | rrf(dense+bm25) | none | 0.850 | 0.875 | 0.843 | 0.234 | 0.812 | 1856.312 | 0.586 | 69.718 |
| fixed-1000/200 (baseline) | nomic+prefix | rrf(dense+bm25) | none | 0.847 | 0.938 | 0.860 | 0.250 | 0.750 | 3008.156 | 0.578 | 33.115 |
| sentence-600 | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.842 | 0.875 | 0.806 | 0.281 | 0.781 | 2084.188 | 0.570 | 28.925 |
| sentence-600 | bge-small-en-v1.5 | hybrid-0.5 | none | 0.839 | 0.906 | 0.808 | 0.281 | 0.781 | 2074.656 | 0.891 | 27.665 |
| provision-contextual | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.834 | 0.875 | 0.832 | 0.234 | 0.781 | 2211.969 | 0.605 | 28.968 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.833 | 0.906 | 0.840 | 0.242 | 0.750 | 3048.281 | 0.590 | 28.591 |
| fixed-1000/200 (baseline) | - | bm25 | none | 0.769 | 0.875 | 0.784 | 0.234 | 0.656 | 2954.438 | 0.766 | 1.174 |
| fixed-500/100 | - | bm25 | none | 0.742 | 0.812 | 0.721 | 0.227 | 0.656 | 1597.438 | 0.750 | 1.706 |
| structure | - | bm25 | none | 0.738 | 0.844 | 0.755 | 0.227 | 0.656 | 1828.531 | 0.797 | 1.160 |
| provision-contextual | - | bm25 | none | 0.737 | 0.812 | 0.742 | 0.219 | 0.656 | 2159.375 | 0.727 | 1.352 |
| sentence-600 | - | bm25 | none | 0.735 | 0.812 | 0.702 | 0.258 | 0.656 | 2087.844 | 0.812 | 1.270 |

## Split: all

| chunker | embedder | retrieval | rerank | mrr | recall@4 | ndcg@4 | precision@4 | hit@1 | context_chars@4 | auroc_answerable | latency_ms_mean |
|---|---|---|---|---|---|---|---|---|---|---|---|
| structure | nomic+prefix | dense | none | 0.928 | 0.977 | 0.931 | 0.262 | 0.875 | 1840.531 | 0.826 | 32.347 |
| fixed-500/100 | nomic+prefix | dense | none | 0.917 | 0.945 | 0.894 | 0.285 | 0.875 | 1621.969 | 0.848 | 32.842 |
| sentence-600 | nomic+prefix | dense | none | 0.910 | 0.945 | 0.886 | 0.309 | 0.859 | 2046.203 | 0.816 | 32.351 |
| structure | nomic (baseline) | dense | none | 0.908 | 0.969 | 0.919 | 0.258 | 0.844 | 1805.031 | 0.850 | 68.439 |
| structure | bge-small-en-v1.5 | dense | none | 0.897 | 0.953 | 0.909 | 0.254 | 0.844 | 1884.156 | 0.910 | 27.652 |
| provision-contextual | bge-small-en-v1.5 | dense | none | 0.894 | 0.953 | 0.906 | 0.254 | 0.828 | 2206.438 | 0.902 | 27.654 |
| sentence-600 | bge-small-en-v1.5 | dense | none | 0.889 | 0.930 | 0.870 | 0.297 | 0.844 | 2071.266 | 0.879 | 27.651 |
| provision-contextual | nomic (baseline) | dense | none | 0.887 | 0.969 | 0.905 | 0.258 | 0.812 | 2208.094 | 0.857 | 68.390 |
| fixed-500/100 | bge-small-en-v1.5 | dense | none | 0.883 | 0.914 | 0.860 | 0.266 | 0.844 | 1448.156 | 0.900 | 27.906 |
| sentence-600 | nomic (baseline) | dense | none | 0.881 | 0.938 | 0.860 | 0.301 | 0.797 | 2062.219 | 0.844 | 68.824 |
| fixed-500/100 | nomic (baseline) | dense | none | 0.879 | 0.922 | 0.860 | 0.266 | 0.828 | 1522.109 | 0.855 | 71.519 |
| provision-contextual | nomic+prefix | dense | none | 0.878 | 0.969 | 0.896 | 0.258 | 0.781 | 2171.422 | 0.799 | 32.353 |
| fixed-1000/200 (baseline) | nomic (baseline) | hybrid-0.5 | none | 0.873 | 0.953 | 0.885 | 0.254 | 0.781 | 3011.781 | 0.799 | 68.765 |
| fixed-1000/200 (baseline) | nomic (baseline) | dense | none | 0.867 | 0.953 | 0.881 | 0.254 | 0.766 | 2990.656 | 0.758 | 68.738 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | dense | none | 0.863 | 0.906 | 0.863 | 0.238 | 0.797 | 3103.156 | 0.805 | 27.437 |
| structure | nomic+prefix | hybrid-0.5 | none | 0.858 | 0.930 | 0.861 | 0.250 | 0.781 | 1826.281 | 0.844 | 32.361 |
| fixed-1000/200 (baseline) | nomic+prefix | dense | none | 0.857 | 0.922 | 0.861 | 0.242 | 0.766 | 3035.766 | 0.727 | 31.940 |
| fixed-1000/200 (baseline) | nomic (baseline) | rrf(dense+bm25) | none | 0.846 | 0.914 | 0.851 | 0.242 | 0.750 | 2990.719 | 0.734 | 71.111 |
| sentence-600 | nomic (baseline) | hybrid-0.5 | none | 0.845 | 0.891 | 0.820 | 0.289 | 0.781 | 2082.547 | 0.857 | 68.844 |
| fixed-1000/200 (baseline) | nomic+prefix | hybrid-0.5 | none | 0.844 | 0.945 | 0.863 | 0.250 | 0.750 | 3007.547 | 0.785 | 31.950 |
| fixed-1000/200 (baseline) | nomic+prefix | rrf(dense+bm25) | none | 0.839 | 0.922 | 0.850 | 0.246 | 0.750 | 3016.859 | 0.719 | 33.115 |
| structure | nomic (baseline) | hybrid-0.5 | none | 0.838 | 0.922 | 0.852 | 0.246 | 0.750 | 1830.328 | 0.867 | 68.455 |
| provision-contextual | nomic (baseline) | hybrid-0.5 | none | 0.837 | 0.922 | 0.850 | 0.246 | 0.750 | 2172.281 | 0.891 | 68.403 |
| provision-contextual | nomic+prefix | hybrid-0.5 | none | 0.834 | 0.938 | 0.851 | 0.250 | 0.734 | 2180.750 | 0.848 | 32.367 |
| fixed-500/100 | nomic+prefix | hybrid-0.5 | none | 0.832 | 0.883 | 0.803 | 0.262 | 0.766 | 1621.500 | 0.812 | 32.861 |
| provision-contextual | bge-small-en-v1.5 | hybrid-0.5 | none | 0.832 | 0.922 | 0.847 | 0.246 | 0.750 | 2183.156 | 0.918 | 27.668 |
| sentence-600 | nomic+prefix | hybrid-0.5 | none | 0.829 | 0.898 | 0.804 | 0.289 | 0.750 | 2086.391 | 0.857 | 32.366 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | hybrid-0.5 | none | 0.829 | 0.891 | 0.831 | 0.234 | 0.750 | 3046.859 | 0.844 | 27.448 |
| structure | nomic+prefix | rrf(dense+bm25) | none | 0.823 | 0.875 | 0.822 | 0.234 | 0.750 | 1864.094 | 0.663 | 33.515 |
| structure | nomic (baseline) | rrf(dense+bm25) | none | 0.821 | 0.867 | 0.819 | 0.230 | 0.750 | 1846.359 | 0.670 | 69.718 |
| structure | bge-small-en-v1.5 | hybrid-0.5 | none | 0.817 | 0.906 | 0.830 | 0.242 | 0.734 | 1863.484 | 0.900 | 27.666 |
| provision-contextual | nomic (baseline) | rrf(dense+bm25) | none | 0.814 | 0.836 | 0.802 | 0.223 | 0.750 | 2194.469 | 0.670 | 69.697 |
| provision-contextual | nomic+prefix | rrf(dense+bm25) | none | 0.813 | 0.852 | 0.808 | 0.227 | 0.750 | 2204.266 | 0.660 | 33.662 |
| provision-contextual | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.811 | 0.852 | 0.806 | 0.227 | 0.750 | 2212.641 | 0.756 | 28.968 |
| sentence-600 | nomic (baseline) | rrf(dense+bm25) | none | 0.809 | 0.852 | 0.775 | 0.270 | 0.750 | 2090.500 | 0.703 | 70.597 |
| fixed-500/100 | nomic (baseline) | rrf(dense+bm25) | none | 0.809 | 0.828 | 0.774 | 0.238 | 0.766 | 1579.438 | 0.667 | 74.422 |
| fixed-500/100 | bge-small-en-v1.5 | hybrid-0.5 | none | 0.809 | 0.852 | 0.779 | 0.242 | 0.750 | 1556.734 | 0.891 | 27.925 |
| fixed-500/100 | nomic+prefix | rrf(dense+bm25) | none | 0.809 | 0.836 | 0.778 | 0.246 | 0.750 | 1612.359 | 0.656 | 34.086 |
| structure | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.807 | 0.859 | 0.806 | 0.230 | 0.750 | 1892.641 | 0.712 | 28.813 |
| fixed-500/100 | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.807 | 0.828 | 0.769 | 0.234 | 0.766 | 1551.234 | 0.778 | 29.152 |
| sentence-600 | bge-small-en-v1.5 | hybrid-0.5 | none | 0.805 | 0.883 | 0.779 | 0.270 | 0.734 | 2089.078 | 0.889 | 27.665 |
| fixed-500/100 | nomic (baseline) | hybrid-0.5 | none | 0.805 | 0.859 | 0.784 | 0.246 | 0.734 | 1578.562 | 0.881 | 71.569 |
| sentence-600 | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.801 | 0.836 | 0.756 | 0.258 | 0.734 | 2090.141 | 0.714 | 28.925 |
| sentence-600 | nomic+prefix | rrf(dense+bm25) | none | 0.799 | 0.859 | 0.776 | 0.273 | 0.734 | 2089.328 | 0.681 | 33.664 |
| fixed-1000/200 (baseline) | bge-small-en-v1.5 | rrf(dense+bm25) | none | 0.799 | 0.859 | 0.797 | 0.227 | 0.703 | 3078.969 | 0.746 | 28.591 |
| fixed-1000/200 (baseline) | - | bm25 | none | 0.727 | 0.812 | 0.730 | 0.215 | 0.609 | 2994.219 | 0.814 | 1.174 |
| sentence-600 | - | bm25 | none | 0.723 | 0.781 | 0.686 | 0.234 | 0.656 | 2091.578 | 0.828 | 1.270 |
| structure | - | bm25 | none | 0.716 | 0.797 | 0.724 | 0.211 | 0.641 | 1860.156 | 0.809 | 1.160 |
| provision-contextual | - | bm25 | none | 0.715 | 0.797 | 0.722 | 0.211 | 0.641 | 2186.891 | 0.779 | 1.352 |
| fixed-500/100 | - | bm25 | none | 0.711 | 0.766 | 0.689 | 0.215 | 0.641 | 1524.234 | 0.791 | 1.706 |

## As-deployed baseline (server flow with relevance gate)

| split | recall (chunks passed) | false refusal | correct refusal | mean chunks passed |
|---|---|---|---|---|
| dev | 0.969 | 0.031 | 0.250 | 3.56 |
| test | 0.812 | 0.156 | 0.750 | 2.84 |
| all | 0.891 | 0.094 | 0.500 | 3.20 |
