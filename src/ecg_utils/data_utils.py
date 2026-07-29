"""
Data loading functions
"""


# fmt: off
from typing import Dict, Tuple, Union, List, Optional, Any
import warnings
import pandas as pd
from pathlib import Path
import ecg_utils.common as common
# fmt: on





##################################
#### DATA VALIATION FUNCTIONS ####
##################################

def check_segment_list(segments: List[pd.DataFrame], expected_n_segments: int = 5) -> None:
    if len(segments) != expected_n_segments:
        warnings.warn(f"The number of segments is {len(segments)} and not equal to {expected_n_segments}.")
    if not all([isinstance(segment, pd.DataFrame) for segment in segments]):
        raise ValueError("All elements in the list must be pandas DataFrames.")
    # check that none of the dfs in the list is empty
    if any([segment.empty for segment in segments]):
        raise ValueError("One or more segments are empty.")



################################################
#### DATA LOADING AND PREPARATION FUNCTIONS ####
################################################
    
def preprocess_event_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Preprocesses the event data by performing the following steps:
    1. Removes the first row of the DataFrame and resets the index.
    2. Adds event start and stop markers to the DataFrame.

    Args:
        df (pd.DataFrame): The input DataFrame containing event data.

    Returns:
        pd.DataFrame: The preprocessed DataFrame with event start and stop markers added.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("Input must be a pandas DataFrame.")
    df = df.iloc[1:].reset_index(drop=True)
    df = add_event_start_stop_marker(df)
    return df

def add_event_start_stop_marker(df: pd.DataFrame) -> pd.DataFrame:  
    """
    Adds 'onset' and 'offset' markers to a DataFrame based on the 'Name' column.
    This function modifies the input DataFrame by adding a new column 'on_offset'.
    The first occurrence of each unique value in the 'Name' column is marked as 'onset',
    and subsequent occurrences are marked as 'offset'.
    
    Parameters:
        df (pd.DataFrame): The input DataFrame containing a 'Name' column.
    Returns:
        pd.DataFrame: The modified DataFrame with the 'on_offset' column added.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("Input must be a pandas DataFrame.")
    df.loc[~df['Name'].duplicated(), 'on_offset'] = 'onset'
    df.loc[df['Name'].duplicated(), 'on_offset'] = 'offset'
    
    return df
    


################################
#### SEGMENTATION FUNCTIONS ####
################################
def segment_df(df: pd.DataFrame, pipeline_params: Dict) -> List[pd.DataFrame]:
    """
    Segments a DataFrame into multiple segments based on event information and pipeline parameters.

    Args:
        df (pd.DataFrame): The input DataFrame with a time-based index used for segmentation.
        pipeline_params (Dict): A dictionary containing segmentation configuration and general parameters:
            - 'segmentation' (Dict): Contains event names and details (e.g., 'event_name' and 'default_duration_seconds').
            - 'general' (Dict): Contains 'sampling_frequency', used for calculating offset times if not provided.

    Returns:
        List[pd.DataFrame]: A list of segmented DataFrames, each corresponding to a specific event segment.

    Raises:
        ValueError: If the offset time for a non-baseline segment is not found or if a segment is empty.
    
    Notes:
        - For "Baseline" segments, if the offset time is not found, it is calculated using 
          the `default_duration_seconds` and the `sampling_frequency`.
        - Onset and offset times are retrieved using the `get_event_time_from_dataframe_index` function.

    Example:
        pipeline_params = {
            'segmentation': {
                '1': {'event_name': 'Baseline', 'default_duration_seconds': 10},
                '2': {'event_name': 'TaskA'}
            },
            'general': {
                'sampling_frequency': 1000
            }
        }
        segments = segment_df(df, pipeline_params)
    """
    segments = []
    for _, segment_info_dict in pipeline_params['segmentation'].items():
        # Extract the information from the dictionary. 
        segment_name = segment_info_dict['event_name']
        default_duration_seconds = segment_info_dict.get('default_duration_seconds')
        
        if segment_name == "Baseline":
            default_duration_seconds = int(default_duration_seconds)
        
        # get the onset and offset times (i.e., the row_index)
        event_onset_time = get_event_time_from_dataframe_index(event_name = segment_name, is_onset = True, df = df)
        event_offset_time = get_event_time_from_dataframe_index(event_name = segment_name, is_onset = False, df = df)
        
        if event_onset_time is None and event_offset_time is None:
            Warning(f"Event {segment_name} not found in the DataFrame.")
            continue
        
        if not event_offset_time and segment_name == 'Baseline':
            # if the offset time is not found, use the default duration to calculate the offset time. But only for baseline
            event_offset_time = event_onset_time + (default_duration_seconds * pipeline_params['general']['sampling_frequency'])
        elif event_onset_time and (not event_offset_time) and segment_name != 'Baseline':
            raise ValueError(f"Offset time for segment {segment_name} not found. Please check the event indices.")

        # retrieve the data in between (inclusive bounds) the onset and offset time using the index
        segment = df[(df.index >= event_onset_time) & (df.index < event_offset_time)]
        if segment.empty:
            raise ValueError(f"Segment {segment_name} is empty between {event_onset_time} and {event_offset_time} ms. Please check the event indices.")
            
        segments.append(segment)
    
    return segments
        
    
def get_event_time_from_dataframe_index(event_name: str, is_onset: bool, 
                                        df: pd.DataFrame) -> Optional[int]:
    """
    Retrieves the time index of a specific event from a DataFrame based on its onset or offset status.

    Args:
        event_name (str): The name of the event to look for in the DataFrame.
        is_onset (bool): A boolean indicating whether to search for the 'onset' (True) or 'offset' (False) of the event.
        df (pd.DataFrame): The input DataFrame containing event information with the following required columns:
            - 'event_name': Column indicating the name of the event.
            - 'on_offset': Column indicating whether the event is an 'onset' or 'offset'.
            - The DataFrame index is expected to represent time or row identifiers.

    Returns:
        Optional[int]: The index corresponding to the specified event and type (onset or offset).
        Returns `None` if no matching event is found.

    Raises:
        AssertionError: If the required columns ('event_name', 'on_offset') are missing or input arguments are invalid.

    Example:
        df = pd.DataFrame({
            'event_name': ['Baseline', 'Baseline', 'TaskA', 'TaskA'],
            'on_offset': ['onset', 'offset', 'onset', 'offset']
        }, index=[0, 100, 200, 300])

        event_time = get_event_time_from_dataframe_index('TaskA', True, df)
        # event_time would be 200 for 'TaskA' onset.
    """
    assert 'event_name' in df.columns 
    assert 'on_offset' in df.columns
    assert isinstance(event_name, str)
    assert isinstance(is_onset, bool)

    
    if is_onset:
        row = df[(df['event_name'] == event_name) & (df['on_offset'] == 'onset')]
    else:
        row = df[(df['event_name'] == event_name) & (df['on_offset'] == 'offset')]
    
    if len(row) > 0:
        return row.index[0]
    else:
        return None


