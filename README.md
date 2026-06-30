# f5collector-to-prometheus
simplified AST/otel collector to prometheus scrape endpoint 

Forked from https://github.com/f5devcentral/application-study-tool/tree/9.8 

# Setup
Follows same setup as https://f5devcentral.github.io/application-study-tool/getting_started.html#installation 

# Prometheus setup
Point your prometheus instance to this host IP address on port 9099 

Recommended scrape configs to restore label mapping when using a prometheus exporter: 

```
scrape_configs:
  - job_name: 'otel-exporter'
    scrape_interval: 1m
    static_configs:
      - targets: ['otel-collector-prom-exporter:9099']
    metric_relabel_configs:
    # copy exported_instance value to label instance
    - source_labels: [exported_instance]
      target_label: instance
    # remove exported_instance label
    - action: labeldrop
      regex: ^exported_instance$
    # copy exported_instance value to label job
    - source_labels: [exported_job]
      target_label: job
    # remove exported_instance label
    - action: labeldrop
      regex: ^exported_job$
```