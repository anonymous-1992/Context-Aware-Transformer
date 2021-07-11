import torch
import numpy as np
import utils as util
import base
import pandas as pd
import random
InputTypes = base.InputTypes


random.seed(1)
torch.manual_seed(1)
np.random.seed(1)


def batching(batch_size, x_en, x_de, y_t, test_id):

    batch_n = int(x_en.shape[0] / batch_size)
    start = x_en.shape[0] % batch_n
    X_en = torch.zeros(batch_n, batch_size, x_en.shape[1], x_en.shape[2])
    X_de = torch.zeros(batch_n, batch_size, x_de.shape[1], x_de.shape[2])
    Y_t = torch.zeros(batch_n, batch_size, y_t.shape[1], y_t.shape[2])
    tst_id = np.empty((batch_n, batch_size, test_id.shape[1], x_en.shape[2]), dtype=object)

    for i in range(batch_n):
        X_en[i, :, :, :] = x_en[start:start+batch_size, :, :]
        X_de[i, :, :, :] = x_de[start:start+batch_size, :, :]
        Y_t[i, :, :, :] = y_t[start:start+batch_size, :, :]
        tst_id[i, :, :, :] = test_id[start:start+batch_size, :, :]
        start += batch_size

    return X_en, X_de, Y_t, tst_id


def batch_sampled_data(data, max_samples, time_steps, num_encoder_steps, column_definition):
    """Samples segments into a compatible format.
    Args:
      data: Sources data to sample and batch
      max_samples: Maximum number of samples in batch
    Returns:
      Dictionary of batched data with the maximum samples specified.
    """

    if max_samples < 1:
        raise ValueError(
          'Illegal number of samples specified! samples={}'.format(max_samples))

    id_col = util.get_single_col_by_input_type(InputTypes.ID, column_definition)
    time_col = util.get_single_col_by_input_type(InputTypes.TIME, column_definition)

    data.sort_values(by=[id_col, time_col], inplace=True)

    valid_sampling_locations = []
    split_data_map = {}
    for identifier, df in data.groupby(id_col):
        num_entries = len(df)
        if num_entries >= time_steps:
            valid_sampling_locations += [
                (identifier, time_steps + i)
                for i in range(num_entries - time_steps + 1)
            ]

            split_data_map[identifier] = df

    if 0 < max_samples < len(valid_sampling_locations):
        ranges = [
          valid_sampling_locations[i] for i in np.random.choice(
              len(valid_sampling_locations), max_samples, replace=False)
        ]
    else:
        print('Max samples={} exceeds # available segments={}'.format(
          max_samples, len(valid_sampling_locations)))
        ranges = valid_sampling_locations

    id_col = util.get_single_col_by_input_type(InputTypes.ID, column_definition)
    time_col = util.get_single_col_by_input_type(InputTypes.TIME, column_definition)
    target_col = util.get_single_col_by_input_type(InputTypes.TARGET, column_definition)
    input_cols = [
        tup[0]
        for tup in column_definition
        if tup[2] not in {InputTypes.ID, InputTypes.TIME}
    ]
    input_size = len(input_cols)
    inputs = np.zeros((max_samples, time_steps, input_size))
    outputs = np.zeros((max_samples, time_steps, 1))
    time = np.empty((max_samples, time_steps, 1), dtype=object)
    identifiers = np.empty((max_samples, time_steps, 1), dtype=object)

    for i, tup in enumerate(ranges):
        if (i + 1 % 1000) == 0:
            print(i + 1, 'of', max_samples, 'samples done...')
        identifier, start_idx = tup
        sliced = split_data_map[identifier].iloc[start_idx -
                                               time_steps:start_idx]
        inputs[i, :, :] = sliced[input_cols]
        outputs[i, :, :] = sliced[[target_col]]
        time[i, :, 0] = sliced[time_col]
        identifiers[i, :, 0] = sliced[id_col]

    sampled_data = {
        'inputs': inputs,
        'outputs': outputs[:, num_encoder_steps:, :],
        'active_entries': np.ones_like(outputs[:, num_encoder_steps:, :]),
        'time': time,
        'identifier': identifiers
    }

    return sampled_data


def inverse_output(predictions, outputs, test_id):

    def format_outputs(preds):
        flat_prediction = pd.DataFrame(
            preds[:, :, 0],
            columns=[
                't+{}'.format(i)
                for i in range(preds.shape[1])
            ]
        )
        flat_prediction['identifier'] = test_id[:, 0, 0]
        return flat_prediction

    process_map = {'predictions': format_outputs(predictions), 'targets': format_outputs(outputs)}
    return process_map


def quantile_loss(y, y_pred, quantile, device):

    zeros = torch.zeros(y.shape).to(device)
    prediction_underflow = y - y_pred
    q_loss = quantile * torch.max(prediction_underflow, zeros) + \
             (1 - quantile) * torch.max(-prediction_underflow, zeros)
    q_loss = q_loss.mean()
    normaliser = y.abs().mean()
    return 2 * q_loss / normaliser