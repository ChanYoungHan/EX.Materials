### Setup
Setup
```bash
uv init --name time_series_analysis
uv add jupyter pandas numpy matplotlib seaborn plotly scikit-learn
uv run python -m ipykernel install --user --name time_series_analysis --display-name "Time Series Analysis (UV)"
```
Exceute Server
```bash
uv run jupyter notebook --no-browser --port=8888
```     
