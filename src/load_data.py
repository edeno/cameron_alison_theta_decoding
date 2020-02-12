import os
from logging import getLogger

import networkx as nx
import numpy as np
import pandas as pd
from scipy.io import loadmat

from loren_frank_data_processing import (get_all_multiunit_indicators,
                                         make_tetrode_dataframe)
from loren_frank_data_processing.core import reconstruct_time
from loren_frank_data_processing.position import (_calulcate_linear_position,
                                                  _get_pos_dataframe,
                                                  calculate_linear_velocity)
from loren_frank_data_processing.track_segment_classification import (
    calculate_linear_distance, classify_track_segments)
from src.parameters import ANIMALS, EDGE_ORDER, EDGE_SPACING

logger = getLogger(__name__)


def get_interpolated_position_info(
        epoch_key, animals, route_euclidean_distance_scaling=1,
        sensor_std_dev=5, diagonal_bias=0.5, edge_spacing=EDGE_SPACING,
        edge_order=EDGE_ORDER,):
    position_info = _get_pos_dataframe(epoch_key, animals)

    position_info = position_info.resample('2ms').mean().interpolate('time')
    position_info.loc[
        position_info.speed < 0, 'speed'] = 0.0
    track_graph, center_well_id = make_track_graph()
    position = position_info.loc[:, ['x_position', 'y_position']].values

    track_segment_id = classify_track_segments(
        track_graph, position,
        route_euclidean_distance_scaling=route_euclidean_distance_scaling,
        sensor_std_dev=sensor_std_dev,
        diagonal_bias=diagonal_bias)
    position_info['linear_distance'] = calculate_linear_distance(
        track_graph, track_segment_id, center_well_id, position)
    position_info['track_segment_id'] = track_segment_id
    position_info['linear_position'] = _calulcate_linear_position(
        position_info.linear_distance.values,
        position_info.track_segment_id.values, track_graph, center_well_id,
        edge_order=edge_order, edge_spacing=edge_spacing)

    position_info['linear_velocity'] = calculate_linear_velocity(
        position_info.linear_distance, smooth_duration=0.500,
        sampling_frequency=500)
    position_info['linear_speed'] = np.abs(position_info.linear_velocity)

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


def load_data(epoch_key):
    logger.info('Loading position information and linearizing...')
    position_info = get_interpolated_position_info(epoch_key, ANIMALS)

    logger.info('Loading multiunits...')
    tetrode_info = make_tetrode_dataframe(
        ANIMALS).xs(epoch_key, drop_level=False)
    tetrode_keys = tetrode_info.loc[tetrode_info.area == 'ca1'].index

    def _time_function(*args, **kwargs):
        return position_info.index

    multiunits = get_all_multiunit_indicators(
        tetrode_keys, ANIMALS, _time_function)

    is_ref = (tetrode_info.reset_index()
              .tetrode_number.isin(tetrode_info.ref.dropna().unique())).values
    ref_tetrode_key = tetrode_info.loc[is_ref].index[0]
    theta_df = get_filter(ref_tetrode_key, ANIMALS, freq_band='theta')

    return {
        'position_info': position_info,
        'multiunits': multiunits,
        'theta': theta_df,
    }


def get_filter_filename(tetrode_key, animals, freq_band='theta'):
    '''Returns a file name for the filtered LFP for an epoch.

    Parameters
    ----------
    tetrode_key : tuple
        Unique key identifying the tetrode. Elements are
        (animal_short_name, day, epoch, tetrode_number).
    animals : dict of named-tuples
        Dictionary containing information about the directory for each
        animal. The key is the animal_short_name.

    Returns
    -------
    filename : str
        File path to tetrode file LFP
    '''
    animal, day, epoch, tetrode_number = tetrode_key
    filename = (f'{animals[animal].short_name}{freq_band}{day:02d}-{epoch}-'
                f'{tetrode_number:02d}.mat')
    return os.path.join(animals[animal].directory, 'EEG', filename)


def get_filter(tetrode_key, animals, freq_band='theta'):
    filter_file = loadmat(
        get_filter_filename(tetrode_key, animals, freq_band))
    filter_data = filter_file[freq_band][0, -1][0, -1][0, -1][0]
    time = reconstruct_time(
        filter_data['starttime'][0][0][0],
        filter_data['data'][0].shape[0],
        float(filter_data['samprate'][0][0][0]))

    COLUMNS = ['bandpassed_lfp', 'instantaneous_phase', 'envelope_magnitude']
    df = pd.DataFrame(filter_data['data'][0], columns=COLUMNS, index=time)

    return df
