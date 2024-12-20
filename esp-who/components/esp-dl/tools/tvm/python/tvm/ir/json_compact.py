# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Tool to upgrade json from historical versions."""
import json
import tvm.ir
import tvm.runtime


def create_updater(node_map, from_ver, to_ver):
    """Create an updater to update json loaded data.

    Parameters
    ----------
    node_map : Map[str, Function]
        Map from type_key to updating function

    from_ver : str
        Prefix of version that we can accept,

    to_ver : str
        The target version.

    Returns
    -------
    fupdater : function
        The updater function
    """

    def _updater(data):
        assert data["attrs"]["tvm_version"].startswith(from_ver)
        nodes = data["nodes"]
        for idx, item in enumerate(nodes):
            f = node_map.get(item["type_key"], None)
            if isinstance(f, list):
                for fpass in f:
                    item = fpass(item, nodes)
            elif f:
                item = f(item, nodes)
            nodes[idx] = item
        data["attrs"]["tvm_version"] = to_ver
        return data

    return _updater


def create_updater_08_to_09():
    """
    Create an update to upgrade json from v0.8 to v0.9

    Returns
    -------
    fupdater : function
        The updater function
    """

    def _initialize_virtual_device(item, _):
        if "virtual_device_" not in item["attrs"]:
            item["attrs"]["virtual_device_"] = "0"
        return item

    node_map = {
        # Base IR
        "GlobalVar": _initialize_virtual_device,
        "relay.Var": _initialize_virtual_device,
        "relay.Function": _initialize_virtual_device,
        "relay.Tuple": _initialize_virtual_device,
        "relay.Call": _initialize_virtual_device,
        "relay.Let": _initialize_virtual_device,
        "relay.If": _initialize_virtual_device,
        "relay.TupleGetItem": _initialize_virtual_device,
        "relay.RefCreate": _initialize_virtual_device,
        "relay.RefRead": _initialize_virtual_device,
        "relay.RefWrite": _initialize_virtual_device,
        "relay.Match": _initialize_virtual_device,
        "relay.Constant": _initialize_virtual_device,
    }

    return create_updater(node_map, "0.8", "0.9")


def create_updater_07_to_08():
    """Create an update to upgrade json from v0.7 to v0.8"""

    def _initialize_module_attributes(item, _):
        assert item["type_key"] == "IRModule", "Only initialize the attributes for IRModules"
        if "attrs" not in item["attrs"]:
            item["attrs"]["attrs"] = "0"
        return item

    node_map = {"IRModule": _initialize_module_attributes}
    return create_updater(node_map, "0.7", "0.8")


def create_updater_06_to_07():
    """Create an update to upgrade json from v0.6 to v0.7

    Returns
    -------
    fupdater : function
        The updater function
    """

    def _ftype_var(item, nodes):
        vindex = int(item["attrs"]["var"])
        item["attrs"]["name_hint"] = nodes[vindex]["attrs"]["name"]
        # set vindex to null
        nodes[vindex]["type_key"] = ""
        del item["attrs"]["var"]
        assert item["type_key"].startswith("relay.")
        item["type_key"] = item["type_key"][len("relay.") :]
        return item

    def _rename(new_name):
        def _convert(item, _):
            item["type_key"] = new_name
            return item

        return _convert

    def _update_tir_var(new_name):
        def _convert(item, _):
            item["type_key"] = new_name
            item["attrs"]["type_annotation"] = "0"
            return item

        return _convert

    def _update_global_key(item, _):
        if "global_key" in item:
            item["repr_str"] = item["global_key"]
            del item["global_key"]
        return item

    def _update_from_std_str(key):
        def _convert(item, nodes):
            str_val = item["attrs"][key]
            jdata = json.loads(tvm.ir.save_json(tvm.runtime.String(str_val)))
            root_idx = jdata["root"]
            val = jdata["nodes"][root_idx]
            sidx = len(nodes)
            nodes.append(val)
            item["attrs"][key] = f"{sidx}"
            return item

        return _convert

    node_map = {
        # Base IR
        "SourceName": _update_global_key,
        "EnvFunc": _update_global_key,
        "relay.Op": [_update_global_key, _rename("Op")],
        "relay.TypeVar": [_ftype_var, _update_from_std_str("name_hint")],
        "TypeVar": _update_from_std_str("name_hint"),
        "relay.Id": [_update_from_std_str("name_hint")],
        "relay.GlobalTypeVar": [_ftype_var, _update_from_std_str("name_hint")],
        "GlobalTypeVar": _update_from_std_str("name_hint"),
        "relay.Type": _rename("Type"),
        "relay.TupleType": _rename("TupleType"),
        "relay.TypeConstraint": _rename("TypeConstraint"),
        "relay.FuncType": _rename("FuncType"),
        "relay.IncompleteType": _rename("IncompleteType"),
        "relay.TypeRelation": _rename("TypeRelation"),
        "relay.TypeCall": _rename("TypeCall"),
        "relay.Constructor": _update_from_std_str("name_hint"),
        "relay.Module": _rename("IRModule"),
        "relay.SourceName": _rename("SourceName"),
        "relay.Span": _rename("Span"),
        "relay.GlobalVar": [_rename("GlobalVar"), _update_from_std_str("name_hint")],
        "GlobalVar": _update_from_std_str("name_hint"),
        "relay.Pass": _rename("transform.Pass"),
        "relay.PassInfo": _rename("transform.PassInfo"),
        "relay.PassContext": _rename("transform.PassContext"),
        "relay.ModulePass": _rename("transform.ModulePass"),
        "relay.Sequential": _rename("transform.Sequential"),
        "StrMap": _rename("Map"),
        # TIR
        "Variable": [_update_tir_var("tir.Var"), _update_from_std_str("name")],
        "SizeVar": [_update_tir_var("tir.SizeVar"), _update_from_std_str("name")],
        "StringImm": [_rename("tir.StringImm"), _update_from_std_str("value")],
        "Cast": _rename("tir.Cast"),
        "Add": _rename("tir.Add"),
        "Sub": _rename("tir.Sub"),
        "Mul": _rename("tir.Mul"),
        "Div": _rename("tir.Div"),
        "Mod": _rename("tir.Mod"),
        "FloorDiv": _rename("tir.FloorDiv"),
        "FloorMod": _rename("tir.FloorMod"),
        "Min": _rename("tir.Min"),
        "Max": _rename("tir.Max"),
        "EQ": _rename("tir.EQ"),
        "NE": _rename("tir.NE"),
        "LT": _rename("tir.LT"),
        "LE": _rename("tir.LE"),
        "GT": _rename("tir.GT"),
        "GE": _rename("tir.GE"),
        "And": _rename("tir.And"),
        "Or": _rename("tir.Or"),
        "Not": _rename("tir.Not"),
        "Select": _rename("tir.Select"),
        "BufferLoad": _rename("tir.BufferLoad"),
        "Ramp": _rename("tir.Ramp"),
        "Broadcast": _rename("tir.Broadcast"),
        "Shuffle": _rename("tir.Shuffle"),
        "Call": [_rename("tir.Call"), _update_from_std_str("name")],
        "Let": _rename("tir.Let"),
        "Any": _rename("tir.Any"),
        "LetStmt": _rename("tir.LetStmt"),
        "AssertStmt": _rename("tir.AssertStmt"),
        "BufferStore": _rename("tir.BufferStore"),
        "BufferRealize": _rename("tir.BufferRealize"),
        "Allocate": _rename("tir.Allocate"),
        "IfThenElse": _rename("tir.IfThenElse"),
        "Evaluate": _rename("tir.Evaluate"),
        "Prefetch": _rename("tir.Prefetch"),
        "AttrStmt": [_rename("tir.AttrStmt"), _update_from_std_str("attr_key")],
        "Layout": [_rename("tir.Layout"), _update_from_std_str("name")],
        "Buffer": [
            _rename("tir.Buffer"),
            _update_from_std_str("name"),
            _update_from_std_str("scope"),
        ],
    }
    return create_updater(node_map, "0.6", "0.7")


def upgrade_json(json_str):
    """Update json from a historical version.

    Parameters
    ----------
    json_str : str
        A historical json file.

    Returns
    -------
    updated_json : str
        The updated version.
    """
    data = json.loads(json_str)
    from_version = data["attrs"]["tvm_version"]

    if from_version.startswith("0.6"):
        data = create_updater_08_to_09()(create_updater_07_to_08()(create_updater_06_to_07()(data)))
    elif from_version.startswith("0.7"):
        data = create_updater_08_to_09()(create_updater_07_to_08()(data))
    elif from_version.startswith("0.8"):
        data = create_updater_08_to_09()(data)
    else:
        raise ValueError(f"Cannot update from version {from_version}")
    return json.dumps(data, indent=2)
