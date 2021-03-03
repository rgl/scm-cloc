This counts the number of source code lines that are inside the given repositories branches.

## Usage

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
wget -qO cloc.pl https://github.com/AlDanial/cloc/releases/download/1.88/cloc-1.88.pl
```

Install extra dependencies on Windows:

```bash
choco install -y strawberryperl
```

See the cloc language definitions:

```bash
perl cloc.pl --write-lang-def=cloc-lang-def.txt
```

Run this tool:

```bash
python3 main.py -v loc -o loc.json <<'EOF'
https://github.com/rgl/packer-provisioner-windows-update.git
https://github.com/rgl/dotnet-core-single-file-console-app.git
https://github.com/rgl/tls-dump-clienthello.git
https://github.com/rgl/youtube-converter.git
https://github.com/rgl/PowerShellExporter.git
https://github.com/rgl/debian-live-builder-vagrant.git
https://github.com/go-gitea/gitea.git
EOF
python3 main.py -v csv -i loc.json -o loc.csv
python3 main.py -v html -i loc.json -o loc.html
```
