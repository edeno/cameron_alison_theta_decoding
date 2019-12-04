import networkx as nx
import numpy as np
import pandas as pd

from loren_frank_data_processing import (get_all_multiunit_indicators,
                                         make_tetrode_dataframe)
from loren_frank_data_processing.position import _get_pos_dataframe
from loren_frank_data_processing.track_segment_classification import (calculate_linear_distance,
                                                                      classify_track_segments)


def get_interpolated_position_info(epoch_key, animals):
    position_info = _get_pos_dataframe(epoch_key, animals)

    position = position_info.loc[:, ['x_position', 'y_position']].values
    track_graph, center_well_id = make_track_graph()
    track_segment_id = classify_track_segments(
        track_graph, position, route_euclidean_distance_scaling=0.1,
        sensor_std_dev=10)
    track_segment_id = pd.DataFrame(
        track_segment_id, index=position_info.index)

    position_info['linear_distance'] = calculate_linear_distance(
        track_graph, track_segment_id.values.squeeze(), center_well_id,
        position)

    position_info = position_info.resample('2ms').mean().interpolate('time')
    position_info.loc[
        position_info.linear_distance < 0, 'linear_distance'] = 0.0
    position_info.loc[
        position_info.speed < 0, 'speed'] = 0.0
    position_info['track_segment_id'] = (
        track_segment_id.reindex(index=position_info.index, method='pad'))

    EDGE_ORDER = [6, 5, 3, 8, 7, 4, 2, 0, 1]
    position_info['linear_position'] = convert_linear_distance_to_linear_position(
        position_info.linear_distance.values,
        position_info.track_segment_id.values, EDGE_ORDER, spacing=15)

    return position_info


def make_track_graph():
    CENTER_WELL_ID = 7

    NODE_POSITIONS = np.array([
        (18.091, 55.053),  # 0 - top left well
        (33.583, 48.357),  # 1 - top middle intersection
        (47.753, 56.512),  # 2 - top right well
        (33.973, 31.406),  # 3 - middle intersection
        (21.166, 21.631),  # 4 - bottom left intersection
        (04.585, 28.966),  # 5 - middle left well
        (48.539, 24.572),  # 6 - middle right intersection
        (22.507, 05.012),  # 7 - bottom left well
        (49.726, 07.439),  # 8 - bottom right well
        (62.755, 33.410),  # 9 - middle right well
    ])

    EDGES = np.array([
        (0, 1),
        (1, 2),
        (1, 3),
        (3, 4),
        (4, 5),
        (3, 6),
        (6, 9),
        (4, 7),
        (6, 8),
    ])

    track_segments = np.array(
        [(NODE_POSITIONS[e1], NODE_POSITIONS[e2]) for e1, e2 in EDGES])
    edge_distances = np.linalg.norm(
        np.diff(track_segments, axis=-2).squeeze(), axis=1)

    track_graph = nx.Graph()

    for node_id, node_position in enumerate(NODE_POSITIONS):
        track_graph.add_node(node_id, pos=tuple(node_position))

    for edge, distance in zip(EDGES, edge_distances):
        nx.add_path(track_graph, edge, distance=distance)

    return track_graph, CENTER_WELL_ID


def load_data(epoch_key, animals):
    position_info = get_interpolated_position_info(epoch_key, animals)

    tetrode_info = (make_tetrode_dataframe(animals)
                    .xs(epoch_key, drop_level=False))
    multiunit = get_all_multiunit_indicators(
        tetrode_info.index, animals, position_info)

    return {
        'position_info': position_info,
        'multiunit': multiunit,
    }


def convert_linear_distance_to_linear_position(
        linear_distance, track_segment_id, edge_order, spacing=30):
    linear_position = linear_distance.copy()

    for prev_edge, cur_edge in zip(edge_order[:-1], edge_order[1:]):
        is_cur_edge = (track_segment_id == cur_edge)
        is_prev_edge = (track_segment_id == prev_edge)

        cur_distance = linear_position[is_cur_edge]
        cur_distance -= cur_distance.min()
        cur_distance += linear_position[is_prev_edge].max() + spacing
        linear_position[is_cur_edge] = cur_distance

    return linear_position
