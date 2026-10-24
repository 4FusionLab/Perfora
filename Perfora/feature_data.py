# SPDX-License-Identifier: GPL-3.0-only
"""Versioned Feature payload; schema 1 remains a single legacy source."""
import json

from .regions import MAX_REGIONS

SCHEMA = 2


def decode(payload):
    data = json.loads(payload)
    if data.get('schema') not in (1, SCHEMA):
        raise ValueError('This Perfora Feature was created by an unsupported version.')
    count = data.get('source_count', 1)
    if (not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_REGIONS
            or data['schema'] == 1 and count != 1):
        raise ValueError('The Feature source count is invalid.')
    if not isinstance(data.get('body_count'), int) or data['body_count'] < 0:
        raise ValueError('The Feature Object count is invalid.')
    if count > 1:
        if data.get('config', {}).get('_source_count') != count:
            raise ValueError('The Feature source metadata is inconsistent.')
        mapping = data['config'].get('_body_map')
        if not isinstance(mapping, list) or len(mapping) != count:
            raise ValueError('The Feature Objects mapping is missing.')
    return data


def metadata(settings, config):
    return dict(schema=SCHEMA, settings={k:v for k,v in settings.__dict__.items() if k not in ('path_samples','guide1','guide2')},
                config={k: v for k, v in config.items()
                        if k not in ('bodies', 'target1', 'target2', '_expressions', 'center_point', 'path', 'guide1', 'guide2')},
                source_count=config.get('_source_count', 1),
                center_selected=config.get('center_point') is not None,
                body_count=len(config['bodies']))
