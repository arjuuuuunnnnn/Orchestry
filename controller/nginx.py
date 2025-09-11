import subprocess
from jinja2 import Template
from pathlib import Path

TEMPLATE = Path("docker/nginx_template.conf").read_text()

class NginxManager:
    def __init__(self, conf_dir="/etc/nginx/conf.d"):
        self.conf_dir = conf_dir

    def update_upstreams(self, app_name, servers):
        tpl = Template(TEMPLATE)
        config = tpl.render(app=app_name, servers=servers)
        conf_path = Path(self.conf_dir) / f"{app_name}.conf"
        conf_path.write_text(config)
        subprocess.run(["nginx", "-t"], check=True)
        subprocess.run(["nginx", "-s", "reload"], check=True)

