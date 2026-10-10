# Run PaperSeek yourself

Community includes the search engine, Web UI, local history, citation maps, and experimental reviews. Choose a Python installation or a persistent Docker service.

## Install the Python package

Requires **Python 3.12 or newer**. The package includes the built Web UI; Node.js is only needed when developing the frontend.

```sh
python -m pip install "paperseek==1.0.0b1"
paperseek serve
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Configure a model and data source in the application.

To install a checkout instead:

```sh
git clone https://github.com/MingfengHong/paperseek.git
cd paperseek
python -m pip install ./backend
paperseek serve
```

For a checkout without built Web assets, follow the [development setup](../contributing.md) to build the frontend before packaging.

## Docker Compose

Use the repository's `compose.yaml`:

```sh
git clone https://github.com/MingfengHong/paperseek.git
cd paperseek
cp .env.example .env
docker compose up -d
```

On PowerShell, replace `cp` with `Copy-Item`. Edit `.env` with your deployment defaults before starting.

The service listens on port **8765** and stores data in the `paperseek-data` volume. Set `PAPERSEEK_VERSION=1.0.0-beta1` in the Compose environment to pin the release; otherwise the supplied Compose file uses `latest`.

```sh
docker compose logs -f paperseek
docker compose stop
docker compose start
```

`docker compose down` keeps the named volume. Adding `--volumes` removes it and its saved data.

## Data and credentials

The default local database is `~/.paperseek/paperseek.db`. Use `--database` or `PAPERSEEK_DATABASE` to choose another path.

Keep the complete data directory together, including artifacts and the local credential encryption key. Do not put it in the source repository or a public file share. Submitted runtime credentials are handled separately from saved research content.

The CLI and local server read process environment variables. They do **not** automatically load a nearby `.env`; Docker Compose explicitly loads the file.

## Separate the API and worker

The default `serve` starts the worker for you. For process supervision, run both processes against the same database:

```sh
paperseek serve --database /srv/paperseek/paperseek.db --no-worker
paperseek worker --database /srv/paperseek/paperseek.db
```

Do not start an additional worker unintentionally by omitting `--no-worker`.

## Network access

The default server binds to loopback. Community is designed for a trusted local environment. Binding `--host 0.0.0.0` or publishing the Docker port exposes it beyond your machine; add appropriate authentication and network controls before sharing access. Community does not become the multi-user Hosted edition by changing its listen address.

## Back up

Stop the API and worker before copying the whole data directory or Docker volume. Restore into a separate location first and verify history, results, and artifacts before replacing a live installation.

Continue with [configuration](../reference/configuration.md) or the [1.0.0-beta1 migration guide](upgrade.md).
