import typer
from loguru import logger


app = typer.Typer()


@app.command()
def get_task_info():
    logger.info("test done")


if __name__ == "__main__":
    app()
