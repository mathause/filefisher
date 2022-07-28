import copy
import glob
import logging
import os

import numpy as np
import pandas as pd
import parse

from .utils import _find_keys, natural_keys, product_dict, update_keys_dict_with_kwargs

logger = logging.getLogger(__name__)

_FILE_FINDER_REPR = """<FileFinder>
path_pattern: '{path_pattern}'
file_pattern: '{file_pattern}'

keys: {repr_keys}
"""


class FinderBase:
    def __init__(self, pattern, suffix=""):

        self.pattern = pattern
        self.keys = _find_keys(pattern)
        self.parser = parse.compile(self.pattern)
        self._suffix = suffix

    def create_name(self, keys=None, **keys_kwargs):
        """build path from keys"""

        keys = update_keys_dict_with_kwargs(keys, **keys_kwargs)

        return self.pattern.format(**keys)


class Finder(FinderBase):
    def _create_condition_dict(self, **kwargs):

        # add wildcard for all undefinded keys
        cond_dict = {key: "*" for key in self.keys}
        cond_dict.update(**kwargs)

        return cond_dict

    def find(self, keys=None, *, _allow_empty=False, **keys_kwargs):

        keys = update_keys_dict_with_kwargs(keys=None, **keys_kwargs)

        # wrap strings in list
        for key, value in keys.items():
            if isinstance(value, str):
                keys[key] = [value]

        list_of_df = list()
        all_patterns = list()
        for one_search_dict in product_dict(**keys):

            cond_dict = self._create_condition_dict(**one_search_dict)
            full_pattern = self.create_name(**cond_dict)

            paths = sorted(self._glob(full_pattern), key=natural_keys)

            df = self._parse_paths(paths)

            # only append if files were found
            if df is not None:
                list_of_df.append(df)

            all_patterns.append(full_pattern)

        if list_of_df:
            df = pd.concat(list_of_df)
            df = df.reset_index(drop=True)
        elif _allow_empty:
            return []
        else:
            msg = "Found no files matching criteria. Tried the following pattern(s):"
            msg += "".join(f"\n- '{pattern}'" for pattern in all_patterns)
            raise ValueError(msg)

        fc = FileContainer(df)

        len_all = len(fc.df)
        len_unique = len(fc.combine_by_key().unique())

        msg = "This query leads to non-unique metadata. Please adjust your query."
        if len_all != len_unique:
            raise ValueError(msg)

        return fc

    @staticmethod
    def _glob(pattern):
        """Return a list of paths matching a pathname pattern

        Notes
        -----
        glob has it's own method so it can be mocked by the tests

        """

        return glob.glob(pattern)

    def _parse_paths(self, paths):

        if not paths:
            return None

        out = list()
        for pth in paths:
            parsed = self.parser.parse(pth)
            out.append([pth + self._suffix] + list(parsed.named.values()))

        keys = ["filename"] + list(parsed.named.keys())

        df = pd.DataFrame(out, columns=keys)
        return df


class FileFinder:
    def __init__(self, path_pattern, file_pattern):

        # cannot search for files (only paths and full)
        self.file = FinderBase(file_pattern)
        # ensure path_pattern ends with a /
        self.path = Finder(os.path.join(path_pattern, ""), suffix="*")
        self.full = Finder(os.path.join(*filter(None, (path_pattern, file_pattern))))

        self.keys_path = self.path.keys
        self.keys_file = self.file.keys
        self.keys = self.full.keys

        self.file_pattern = self.file.pattern
        self.path_pattern = self.path.pattern
        self._full_pattern = self.full.pattern

    def create_path_name(self, keys=None, **keys_kwargs):
        # warnings.warn("'create_path_name' is deprecated, use 'path.name' instead")
        return self.path.create_name(keys, **keys_kwargs)

    def create_file_name(self, keys=None, **keys_kwargs):
        # warnings.warn("'create_file_name' is deprecated, use 'file.name' instead")
        return self.file.create_name(keys, **keys_kwargs)

    def create_full_name(self, keys=None, **keys_kwargs):
        # warnings.warn("'create_full_name' is deprecated, use 'full.name' instead")
        return self.full.create_name(keys, **keys_kwargs)

    def find_paths(self, keys=None, *, _allow_empty=False, **keys_kwargs):
        return self.path.find(keys, _allow_empty=_allow_empty, **keys_kwargs)

    def find_files(self, keys=None, _allow_empty=False, **keys_kwargs):
        return self.full.find(keys, _allow_empty=_allow_empty, **keys_kwargs)

    def __repr__(self):

        repr_keys = "', '".join(sorted(self.full.keys))
        repr_keys = f"'{repr_keys}'"

        msg = _FILE_FINDER_REPR.format(
            path_pattern=self.path.pattern,
            file_pattern=self.file.pattern,
            repr_keys=repr_keys,
        )

        return msg


class FileContainer:
    """docstring for FileContainer"""

    def __init__(self, df):

        self.df = df

    def __iter__(self):

        for index, element in self.df.iterrows():
            yield element["filename"], element.drop("filename").to_dict()

    def __getitem__(self, key):

        if isinstance(key, (int, np.integer)):
            # use iloc -> there can be more than one element with index 0
            element = self.df.iloc[key]

            return element["filename"], element.drop("filename").to_dict()
        # assume slice or [1]
        else:
            ret = copy.copy(self)
            ret.df = self.df.iloc[key]
            return ret

    def combine_by_key(self, keys=None, sep="."):
        """combine colums"""

        if keys is None:
            keys = list(self.df.columns.drop("filename"))

        return self.df[keys].apply(lambda x: sep.join(x.map(str)), axis=1)

    def search(self, **query):

        ret = copy.copy(self)
        ret.df = self._get_subset(**query)
        return ret

    def _get_subset(self, **query):
        if not query:
            return pd.DataFrame(columns=self.df.columns)
        condition = np.ones(len(self.df), dtype=bool)
        for key, val in query.items():
            if isinstance(val, list):
                condition_i = np.zeros(len(self.df), dtype=bool)
                for val_i in val:
                    condition_i = condition_i | (self.df[key] == val_i)
                condition = condition & condition_i
            elif val is not None:
                condition = condition & (self.df[key] == val)
        query_results = self.df.loc[condition]
        return query_results

    def __len__(self):
        return self.df.__len__()

    def __repr__(self):

        msg = "<FileContainer>\n"
        return msg + self.df.__repr__()
