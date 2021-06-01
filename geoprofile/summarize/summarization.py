from typing import List, Union
from shapely import wkt
import numpy as np
import pandas as pd
from math import floor

from geoprofile.forms import BaseSummarizeForm

SAMPLE_CAP = 1 / 100
DEFAULT_NUMBER_OF_BUCKETS = 10


def summarize(gdf, form: BaseSummarizeForm):
    df = pd.DataFrame(gdf.to_geopandas_df().drop(columns='geometry'))
    json_report = {"column_samples": [], "column_histograms": [], "bounding_box_samples": [], "simplified_geometry": []}
    columns_to_sample = form.columns_to_sample.data
    columns_to_hist = form.columns_to_hist.data
    numeric_columns = df._get_numeric_data().columns
    n_samples = form.n_samples.data if form.n_samples.data and form.n_samples.data > 0 else floor(len(df.index) * SAMPLE_CAP)
    if form.n_buckets.data:
        n_buckets = form.n_buckets.data
    else:
        n_buckets = DEFAULT_NUMBER_OF_BUCKETS
    if columns_to_sample:
        sample_type = form.sampling_method.data
        if not sample_type:
            sample_type = 'random'
        for column in df:
            if column in columns_to_sample:
                sample = []
                if sample_type == 'random':
                    sample = random_sampling(df[column], n_samples)
                elif sample_type == 'stratified':
                    sample = stratified_sampling(df[column], n_samples, form.to_stratify.data)
                elif sample_type == 'cluster':
                    sample = cluster_sampling(df[column], form.n_clusters.data,
                                              form.clustering_column_name.data, form.n_sample_per_cluster.data)
                json_report["column_samples"].append({"column_name": column, "sample": sample})
    if form.columns_to_hist.data:
        for column in df:
            if column in columns_to_hist:
                hist = single_column_histogram(df[column], numeric_columns, n_buckets)
                json_report["column_histograms"].append({"column_name": column, "histogram": hist})
    if form.geometry_sampling_bounding_box.data:
        samples = geo_bounding_box_sampling(gdf, df, n_samples, form.geometry_sampling_bounding_box.data, columns_to_sample)
        json_report["bounding_box_samples"] = samples
    if form.geometry_simplification_tolerance.data:
        simplified_geometry = geo_vector_simplification(gdf, form.geometry_simplification_tolerance.data)
        json_report["simplified_geometry"].extend(simplified_geometry)
    return json_report


def random_sampling(df, n_samples: int):
    n = define_dataset_sample_number(df, n_samples)
    return df.sample(n).values.tolist()


def stratified_sampling(df, n_samples: int, to_stratify: Union[str, List[str]]):
    frac = n_samples / len(df.index)
    frac = SAMPLE_CAP if frac > SAMPLE_CAP else frac
    return df.groupby(to_stratify).apply(lambda x: x.sample(frac=frac)).values.tolist()


def cluster_sampling(df, n_clusters: int, clustering_column_name: str, n_sample_per_cluster: int = None):
    n = define_dataset_sample_number_cluster(df, n_clusters, n_sample_per_cluster)
    unique = df[clustering_column_name].unique()
    clusters = np.random.choice(unique, size=n_clusters, replace=False)
    cluster_sample = pd.DataFrame()
    for cluster_id in clusters:
        column_data = df[df[clustering_column_name] == cluster_id]
        column_data_size = len(column_data.index)
        if column_data_size < n:
            n = column_data_size
        cluster_sample = cluster_sample.append(df[df[clustering_column_name] == cluster_id].sample(n))
    return cluster_sample.values.tolist()


def single_column_histogram(column, numeric_columns: list, n_buckets: int):
    if column.name in numeric_columns:
        hist = pd.cut(column, n_buckets).value_counts().sort_index()
    else:
        hist = column.value_counts()
    json_hist = []
    for bucket in hist.index:
        json_hist.append({'bucket': bucket, 'value': hist[bucket]})
    return json_hist


def geo_bounding_box_sampling(gdf, df, n_samples: int, bounding_box: list, columns_to_sample: list):
    try:
        n = define_dataset_sample_number(df, n_samples)
        bbox = list(map(lambda x: float(x), bounding_box))
        samples = gdf.profiler.get_sample(n_obs=n, method="random", bbox=bbox)
        samples['geometry'] = samples.geometry.to_wkt().values()
    except IndexError:
        return []
    else:
        result = samples.to_dict(array_type="list")
        if columns_to_sample:
            return {key: result[key] for key in result.keys() if key in columns_to_sample}
        else:
            return result


def geo_vector_simplification(gdf, tolerance: Union[float, list]):
    simplified_geometry = gdf.constructive.simplify(tolerance, preserve_topology=True)
    str_geometry = list(simplified_geometry.to_geopandas_df().geometry.apply(lambda x: wkt.dumps(x)))
    return str_geometry


def define_dataset_sample_number(df, n_samples: int):
    cap = floor(len(df.index) * SAMPLE_CAP)
    return cap if cap < n_samples else n_samples


def define_dataset_sample_number_cluster(df, n_clusters: int, n_sample_per_cluster: int):
    cluster_cap = floor((len(df.index) * SAMPLE_CAP) / n_clusters)
    if n_sample_per_cluster:
        return cluster_cap if cluster_cap < n_sample_per_cluster else n_sample_per_cluster
    return cluster_cap
