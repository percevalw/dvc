import collections
import re
from ast import literal_eval
from contextlib import contextmanager
from typing import Dict, Any
import json

from funcy import reraise

from ._common import ParseError, _dump_data, _load_data, _modify_data


def join_path(path):
    return ".".join(repr(x) if "." in x else x for x in path)


class ConfigFileCorruptedError(ParseError):
    def __init__(self, path):
        super().__init__(path, "Config file structure is corrupted")


def split_path(path: str):
    offset = 0
    result = []
    for match in re.finditer(r"(?:'([^']*)'|\"([^\"]*)\"|([^.]*))(?:[.]|$)", path):
        assert match.start() == offset, f"Malformed path: {path!r} in config"
        offset = match.end()
        result.append(next((g for g in match.groups() if g is not None)))
        if offset == len(path):
            break
    return result


def config_literal_eval(s: str):
    try:
        return literal_eval(s)
    except (ValueError, SyntaxError):
        try:
            return json.loads(s)
        except ValueError:
            return s

def config_literal_dump(v: Any):
    if isinstance(v, str):
        if config_literal_eval(str(v)) == v:
            return str(v)
        return json.dumps(v)
    return json.dumps(v)
        

def flatten_sections(root: Dict[str, Any]) -> Dict[str, Any]:
    res = collections.defaultdict(lambda: {})

    def rec(d, path):
        res.setdefault(join_path(path), {})
        section = {}
        for k, v in d.items():
            if isinstance(v, dict):
                rec(v, (*path, k))
            else:
                section[k] = v
        res[join_path(path)].update(section)

    rec(root, ())
    res.pop("", None)
    return dict(res)


def load_config(path, fs=None):
    return _load_data(path, parser=parse_config, fs=fs)


def parse_config(text, path, decoder=None):
    import configparser

    with reraise(configparser.Error, ConfigFileCorruptedError(path)):
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        parser.read_string(text)
        config = {}
        for section in parser.sections():
            parts = split_path(section)
            current = config
            for part in parts:
                if part not in current:
                    current[part] = current = dict()
                else:
                    current = current[part]
            current.update({
                k: config_literal_eval(v)
                for k, v in parser.items(section)
            })

    return config


def _dump(data, stream):
    import configparser

    prepared = flatten_sections(data)

    parser = configparser.ConfigParser(interpolation=None)
    
    parser.optionxform = str
    for section_name, section in prepared.items():
        parser.add_section(section_name)
        parser[section_name].update({k: config_literal_dump(v) for k, v in section.items()})

    return parser.write(stream)


def dump_config(path, data, fs=None, **kwargs):
    return _dump_data(path, data, dumper=_dump, fs=fs, **kwargs)


@contextmanager
def modify_config(path, fs=None):
    """
    NOTE: As configparser does not parse comments, those will be striped
    from the modified config file
    """
    with _modify_data(path, parse_config, _dump, fs=fs) as d:
        yield d
