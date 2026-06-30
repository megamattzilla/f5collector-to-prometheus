"""
config_helper.py

A command-line tool for helping simplify application study tool configurations. It takes 2 input files,
one containing defaults that should be applied to each bigip receiver configuration, and a second with
the individual bigip targets and any non-default values to use as overrides.

The output is written to ./services/otel_collector/receivers.yaml (and pipelines.yaml) where the AST
Otel Instance merges them with the base configuration templates.

Key Features:
- Convert legacy JSON configurations to a new YAML format.
- Generate output configurations based on default settings and per-device inputs.
- Supports sharding targets across multiple collector pairs.
- Auto-generates docker-compose.override.yaml for seamless container scaling.
- Supports dry-run mode to preview changes without writing to files.
"""

import argparse
import json
import logging
import yaml
from copy import deepcopy

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

def load_yaml(path):
    try:
        with open(path, "r") as f:
            content = yaml.safe_load(f)
            logging.info("Successfully loaded '%s'.", path)
            return content
    except FileNotFoundError:
        logging.error("Error: The file '%s' does not exist.", path)
        return None
    except PermissionError:
        logging.error("Error: Permission denied when trying to open '%s'.", path)
        return None
    except yaml.YAMLError as e:
        logging.error("Error reading YAML file '%s': %s", path, e)
        return None

def load_json(path):
    try:
        with open(path, "r") as f:
            content = json.loads(f.read())
            logging.info("Successfully loaded '%s'.", path)
            return content
    except FileNotFoundError:
        logging.error("Error: The file '%s' does not exist.", path)
        return None
    except PermissionError:
        logging.error("Error: Permission denied when trying to open '%s'.", path)
        return None
    except json.JSONDecodeError as e:
        logging.error("Error reading JSON file '%s': %s", path, e)
        return None

def write_yaml_to_file(data, path):
    try:
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
            logging.info("Successfully wrote data to '%s'.", path)
    except IOError as e:
        logging.error("Error writing to YAML file '%s': %s", path, e)

def load_default_config(args):
    logging.info("Loading AST Default Settings in %s...", args.default_config_file)
    return load_yaml(args.default_config_file)

def load_receiver_config(args):
    logging.info("Loading Per-Receiver (BigIP) Settings in %s...", args.receiver_input_file)
    return load_yaml(args.receiver_input_file)

def load_legacy_config(args):
    logging.info("Loading legacy configuration in %s...", args.legacy_config_file)
    return load_json(args.legacy_config_file)

def convert_legacy_config(args):
    logging.info("Converting legacy configuration in %s...", args.legacy_config_file)
    default_config = load_default_config(args)
    if not default_config:
        return None

    default_receiver_configs = default_config.get("bigip_receiver_defaults")
    if not default_receiver_configs:
        logging.error("Error: Default receiver configs not found in default settings file.")
        return None

    legacy_config = load_legacy_config(args)
    if not legacy_config:
        return None

    return transform_receiver_configs(legacy_config, default_receiver_configs)

def transform_receiver_configs(legacy_configs, default_configs):
    new_receiver_configs = {}
    for idx, receiver_config in enumerate(legacy_configs):
        new_receiver_configs[f"bigip/{idx + 1}"] = transform_single_receiver(
            receiver_config, default_configs
        )
    return new_receiver_configs

def handle_collection_interval(value, default_value):
    with_seconds = f"{value}s"
    return with_seconds if with_seconds != default_value else None

def handle_password_env_ref(value, default_value):
    escaped_value = f"${{env:{value}}}"
    return escaped_value if escaped_value != default_value else None

def handle_tls_settings(new_receiver_config, key, value, default_configs):
    if key == "tls_insecure_skip_verify":
        default_value = default_configs.get("tls", {}).get("insecure_skip_verify")
        key = "insecure_skip_verify"
    else:
        default_value = default_configs.get("tls", {}).get("ca_file")

    if value != default_value:
        if "tls" not in new_receiver_config:
            new_receiver_config["tls"] = {}
        new_receiver_config["tls"][key] = value

def transform_single_receiver(receiver_config, default_configs):
    new_receiver_config = {}
    for key, value in receiver_config.items():
        default_value = default_configs.get(key)

        if key == "collection_interval":
            interval = handle_collection_interval(value, default_value)
            if interval:
                new_receiver_config[key] = interval
        elif key == "password_env_ref":
            pw = handle_password_env_ref(value, default_value)
            if pw:
                new_receiver_config["password"] = pw
        elif key in ["tls_insecure_skip_verify", "ca_file"]:
            handle_tls_settings(new_receiver_config, key, value, default_configs)
        elif default_value and default_value == value:
            continue
        else:
            new_receiver_config[key] = value

    return new_receiver_config

def deep_merge(dict1, dict2):
    for key, value in dict2.items():
        if key in dict1:
            if isinstance(dict1[key], dict) and isinstance(value, dict):
                deep_merge(dict1[key], value)
            else:
                dict1[key] = value
        else:
            dict1[key] = value
    return dict1

def generate_receiver_configs(receiver_input_configs, default_config):
    merged_config = {}
    for k, v in receiver_input_configs.items():
        defaults = deepcopy(default_config.get("bigip_receiver_defaults"))
        this_cfg = deepcopy(v)
        if this_cfg.get("pipeline"):
            del this_cfg["pipeline"]
        merged_config[k] = deep_merge(defaults, this_cfg)
    return merged_config

def assemble_pipelines(pipeline_key, default_pipeline, receiver_input_configs, pipelines, filename):
    for receiver, config in receiver_input_configs.items():
        pipeline = config.get(pipeline_key, default_pipeline)
        this_pipeline = pipelines.get(pipeline)
        if not this_pipeline:
            logging.error(
                "Pipeline %s on Receiver %s is not found in config pipelines section of %s...",
                pipeline,
                receiver,
                filename,
            )
            return None
        if not this_pipeline.get("receivers"):
            this_pipeline["receivers"] = []
        this_pipeline["receivers"].append(receiver)

def generate_pipeline_configs(receiver_input_configs, default_config, args):
    pipelines = default_config.get("pipelines")
    if not pipelines:
        logging.error("No pipelines set in default config file:\n\n%s", yaml.dump(default_config))
        return None

    default_pipeline = default_config.get("pipeline_default")
    if not default_pipeline:
        logging.error("No default pipeline set in default config file:\n\n%s", yaml.dump(default_config))
        return None

    assemble_pipelines(
        "pipeline",
        default_pipeline,
        receiver_input_configs,
        pipelines,
        args.receiver_input_file,
    )

    f5_pipeline_default = default_config.get("f5_pipeline_default")
    enabled = default_config.get("f5_data_export", False)
    f5_export_enabled = f5_pipeline_default and enabled
    
    if not f5_export_enabled:
        logging.warning(
            "The f5_data_export=true and f5_pipeline_default fields are required to "
            "export metrics periodically to F5. Contact your F5 Sales Rep to provision a "
            "Sensor ID and Access Token."
        )
    else:
        assemble_pipelines(
            "f5_pipeline",
            f5_pipeline_default,
            receiver_input_configs,
            pipelines,
            args.receiver_input_file,
        )

    final_pipelines = {}
    for pipeline, settings in pipelines.items():
        receivers = settings.get("receivers", [])
        if len(receivers) == 0:
            continue
        final_pipelines[pipeline] = settings
    return final_pipelines

def generate_docker_compose_override(num_shards, default_config):
    """Generates a dynamic docker-compose.override.yaml by merging user templates with dynamic sharding data."""
    services = {}
    
    # Fetch user-defined templates from defaults, or use fallbacks if missing
    compose_defaults = default_config.get("docker_compose_defaults", {})
    
    # Grab the user-defined starting port, default to 9090 if missing
    port_start = compose_defaults.get("exporter_port_start", 9090)
    
    scraper_base = compose_defaults.get("scraper_base", {
        "image": "ghcr.io/f5devcentral/application-study-tool/otel_custom_collector:latest",
        "restart": "unless-stopped",
        "command": ["--config=/etc/otel-collector-config/defaults/bigip-scraper-config.yaml"],
        "env_file": [".env.device-secrets"],
        "networks": ["7lc_network"]
    })
    
    exporter_base = compose_defaults.get("exporter_base", {
        "image": "otel/opentelemetry-collector-contrib:0.155.0",
        "restart": "unless-stopped",
        "command": ["--config=/etc/otel-collector-config/defaults/prometheus-exporter-config.yaml"],
        "env_file": [".env.device-secrets"],
        "networks": ["7lc_network"]
    })

    for i in range(1, num_shards + 1):
        # Deep copy to ensure we don't accidentally mutate the base template
        scraper_svc = deepcopy(scraper_base)
        exporter_svc = deepcopy(exporter_base)
        
        # Merge dynamic Scraper properties
        scraper_svc["environment"] = [f"OTLP_TARGET_ENDPOINT=exporter-{i}:4317"]
        scraper_svc["volumes"] = [
            "./services/otel_collector:/etc/otel-collector-config",
            f"./services/otel_collector/receivers_{i}.yaml:/etc/otel-collector-config/receivers.yaml",
            f"./services/otel_collector/pipelines_{i}.yaml:/etc/otel-collector-config/pipelines.yaml"
        ]
        
        # Merge dynamic Exporter properties and calculate the exposed port
        exporter_svc["volumes"] = ["./services/generic_otel_collector:/etc/otel-collector-config"]
        exporter_svc["ports"] = [f"{port_start + i}:9099"]
        
        services[f"scraper-{i}"] = scraper_svc
        services[f"exporter-{i}"] = exporter_svc
    
    return {"services": services}

def generate_configs(args):
    logging.info(
        "Generating configs from %s and %s...",
        args.default_config_file,
        args.receiver_input_file,
    )
    default_config = load_default_config(args)
    receiver_input_configs = load_receiver_config(args)
    
    logging.info("Generating receiver configs...")
    receiver_output_configs = generate_receiver_configs(receiver_input_configs, default_config)
    
    logging.info("Generating pipeline configs...")
    pipeline_output_configs = generate_pipeline_configs(receiver_input_configs, default_config, args)

    # Sharding Logic
    if args.shards > 1:
        sharded_receivers = {i: {} for i in range(1, args.shards + 1)}
        sharded_pipelines = {i: deepcopy(pipeline_output_configs) for i in range(1, args.shards + 1)}

        # Clear out the receivers lists in the copied pipelines
        for i in range(1, args.shards + 1):
            for p_name in sharded_pipelines[i]:
                sharded_pipelines[i][p_name]["receivers"] = []

        # Round-robin distribute the Big-IP receivers across the shards
        for idx, (rec_id, rec_cfg) in enumerate(receiver_output_configs.items()):
            shard_id = (idx % args.shards) + 1
            sharded_receivers[shard_id][rec_id] = rec_cfg

            # Assign this receiver to its designated pipeline in the shard
            for p_name, p_data in pipeline_output_configs.items():
                if rec_id in p_data.get("receivers", []):
                    sharded_pipelines[shard_id][p_name]["receivers"].append(rec_id)

        # Cleanup empty pipelines in shards that might not have received certain receiver types
        for i in range(1, args.shards + 1):
            empty_pipelines = [k for k, v in sharded_pipelines[i].items() if not v.get("receivers")]
            for k in empty_pipelines:
                del sharded_pipelines[i][k]

        return sharded_receivers, sharded_pipelines

    # Standard return format for single shard
    return {1: receiver_output_configs}, {1: pipeline_output_configs}

def get_args():
    parser = argparse.ArgumentParser(
        description="A tool for helping with application study tool configurations."
    )
    parser.add_argument("--convert-legacy-config", action="store_true", help="Convert the legacy big-ips.json to the new format.")
    parser.add_argument("--legacy-config-file", type=str, default="./config/big-ips.json", help="Path to the legacy big-ips.json file.")
    parser.add_argument("--dry-run", action="store_true", help="Don't write output to files")
    parser.add_argument("--default-config-file", type=str, default="./config/ast_defaults.yaml", help="Path to the default settings file.")
    parser.add_argument("--receiver-input-file", type=str, default="./config/bigip_receivers.yaml", help="Path to the receiver settings input file.")
    parser.add_argument("--generate-configs", action="store_true", help="Read files in config directory and write AST Otel Config")
    parser.add_argument("--receiver-output-file", type=str, default="./services/otel_collector/receivers.yaml", help="Path to the receiver settings output file.")
    parser.add_argument("--pipelines-output-file", type=str, default="./services/otel_collector/pipelines.yaml", help="Path to the pipeline settings output file.")
    parser.add_argument("--shards", type=int, default=1, help="Number of shards to split the Big-IP receivers into (default: 1).")
    return parser

def main():
    parser = get_args()
    args = parser.parse_args()

    if args.convert_legacy_config:
        new_receivers = convert_legacy_config(args)
        if not new_receivers:
            return
        logging.info("Converted the legacy config to the following bigip_receivers.yaml output:\n\n%s", yaml.dump(new_receivers, default_flow_style=False))
        if not args.dry_run:
            write_yaml_to_file(new_receivers, args.receiver_input_file)
        return

    if args.generate_configs:
        receivers, pipelines = generate_configs(args)
        if not receivers or not pipelines:
            return
            
        for shard_id in receivers.keys():
            # If shards > 1, append the suffix (e.g., _1, _2). Otherwise, keep normal filename.
            suffix = f"_{shard_id}" if args.shards > 1 else ""
            r_file = args.receiver_output_file.replace(".yaml", f"{suffix}.yaml")
            p_file = args.pipelines_output_file.replace(".yaml", f"{suffix}.yaml")
            
            logging.info("Built the following receiver file for Shard %s:\n\n%s", shard_id, yaml.dump(receivers[shard_id]))
            
            if not args.dry_run:
                write_yaml_to_file(pipelines[shard_id], p_file)
                write_yaml_to_file(receivers[shard_id], r_file)

        # Build and write the Docker Compose Overrides
        if not args.dry_run:
            # Load the defaults so we can extract the compose template
            default_config = load_default_config(args)
            compose_override = generate_docker_compose_override(args.shards, default_config)
            
            write_yaml_to_file(compose_override, "docker-compose.override.yaml")
            logging.info("Successfully built docker-compose.override.yaml for %s shard(s).", args.shards)
            
        return

    logging.info("Found nothing to do... Try running with --convert-legacy-config or --generate-configs...")

if __name__ == "__main__":
    main()