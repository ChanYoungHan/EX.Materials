# install & setup
## for initial settings
1. set-up poetry environment
```bash
pip install poetry
poetry init
```

2. make test scripts
recommand make typer app or fastapi app
```bash
mkdir python_typer_app
touch __init__.py
touch main.py
```

3. create excecute command-line
```bash
echo '[tool.poetry.scripts]
python-typer-app = "python_typer_app.main:app"' >> pyproject.toml
poetry install
```


## for USE
```bash
pip install poetry
poetry install
poetry build
```s

```bash
python_typer_app --help
```

