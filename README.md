# `gorak` 

GORAK — the Greater OpenROAD Application Kit

For developers who enjoy OpenROAD and their hair.

## Early alpha warning

`gorak` is early alpha software.

It is currently useful for experimenting with one-way export of OpenROAD source
into git-friendly files, but it is not production-ready. The `.w4gl`, `.wml`,
`app.json`, and `field_defaults.json` formats are still evolving and may change
without migration tooling.

Do not rely on `gorak` as the only copy of important OpenROAD source. Keep your
OpenROAD source database, XML exports, backups, and normal recovery processes in
place. Import, round-trip sync, and full XML reconstruction are not implemented
yet.

## Setting up for development

1. Clone the repo
```
git clone git@github.com:dougwhite/gorak.git
```

2. Install the dependencies using [uv](https://docs.astral.sh/uv/)
```
cd gorak
uv sync
```

3. Run the tests
```
uv run pytest
```

## Installing and building

For day-to-day local development, install `gorak` as an editable command with:
```
uv tool install --editable .
```

After that, the `gorak` command can be run from outside this source checkout:
```
gorak --help
gorak new my_project
gorak app list --vnode myvnode --database exampledb
```

Because the install is editable, changes under `src/gorak` are picked up without
rebuilding the package. To remove the command:
```
uv tool uninstall gorak
```

To build distribution artifacts:
```
uv build
```

This writes the wheel and source archive to `dist/`. The wheel can be installed
as a standalone `gorak` command with:
```
uv tool install dist/gorak-0.1.0-py3-none-any.whl
```

## CLI helpers

Show the available commands and options with:
```
gorak --help
```

Subcommands also provide their own help, for example:
```
gorak component export --help
```

### Encoding an OpenROAD XML export

You can encode an OpenROAD `.xml` export as `.w4gl` text on stdout:
```
gorak encode tests/fixtures/fm_example_frame.xml
```

Or write the result directly to a file:
```
gorak encode tests/fixtures/fm_example_frame.xml --output fm_example_frame.w4gl
```

### Creating a Gorak project

Create a new Gorak project folder with:
```
gorak new my_project
```

By default this also runs `git init` in the new project. For a temporary project
without its own git repository, use:
```
gorak new --nogit my_project
```

This creates `my_project/gorak.json` and a starter application folder:
```
my_project/
├── .env.example
├── .gitignore
├── field_defaults.json
├── gorak.json
└── my_project
    ├── app.json
    └── p4_init.w4gl
```

The starter `app.json` contains the starting component, description, and an
empty included application list placeholder. The application name is implied by
the folder name.

### Configuring OpenROAD access

Everything local: OpenROAD CLI commands and SQL both run on this machine.
```
gorak config --backend local --vnode myvnode --database exampledb
```
```env
GORAK_BACKEND=local
GORAK_VNODE=myvnode
GORAK_DATABASE=exampledb
```

Everything remote: OpenROAD CLI commands and SQL both run through SSH helpers.
```
gorak config \
  --backend remote \
  --host windows-pc \
  --user test \
  --gorak-root 'C:\Development\gorak' \
  --vnode myvnode \
  --database exampledb
```
```env
GORAK_BACKEND=remote
GORAK_REMOTE_HOST=windows-pc
GORAK_REMOTE_USER=test
GORAK_REMOTE_ROOT=C:\Development\gorak
GORAK_VNODE=myvnode
GORAK_DATABASE=exampledb
```

You can also use Ingres ODBC for improved performance:
```
gorak config \
  --backend local \
  --vnode myvnode \
  --database exampledb \
  --sql-backend odbc \
  --db-driver 'Ingres AC' \
  --db-host db-host.example \
  --db-listen-address II7 \
  --db-user ingres \
  --db-password secret
```
```env
GORAK_BACKEND=local
GORAK_VNODE=myvnode
GORAK_DATABASE=exampledb

GORAK_SQL_BACKEND=odbc
GORAK_DB_DRIVER=Ingres AC
GORAK_DB_HOST=db-host.example
GORAK_DB_LISTEN_ADDRESS=II7
GORAK_DB_USER=ingres
GORAK_DB_PASSWORD=secret
```

Direct SQL requires the Actian Ingres client runtime and ODBC driver.

### Installing Windows SSH helpers

Copy the Windows-side SSH helper files to the configured remote gorak root with:
```
gorak remote install \
  --user test \
  --host WINDOWS-PC \
  --gorak-root 'C:\Development\gorak'
```

When run inside a Gorak project, `remote install` can read `--user`, `--host`,
and `--gorak-root` from the project `.env`. The helper files are packaged with
`gorak`, so this command works from an installed distribution as well as from a
source checkout.

### Listing OpenROAD applications

You can list applications in a source database through either the remote or
local backend:
```
gorak app list \
  --user test \
  --host WINDOWS-PC \
  --gorak-root 'C:\Development\gorak' \
  --vnode myvnode \
  --database exampledb
```

The default output is JSON. CSV is also available:
```
gorak app list \
  --user test \
  --host WINDOWS-PC \
  --gorak-root 'C:\Development\gorak' \
  --vnode myvnode \
  --database exampledb \
  --format csv
```

### Listing OpenROAD components

List the components in one OpenROAD application:
```
gorak component list \
  --user test \
  --host WINDOWS-PC \
  --gorak-root 'C:\Development\gorak' \
  --vnode myvnode \
  --database exampledb \
  application
```

The default output is JSON. CSV is also available with `--format csv`.

### Listing included applications

List ordered application includes for one OpenROAD application:
```
gorak includes list \
  --vnode myvnode \
  --database exampledb \
  application
```

Source database includes are emitted as strings. Image/package includes are
emitted as objects with `name` and `image`. OpenROAD's automatic `core.plb`
include is omitted.

### Field defaults

New projects include a repo-level `field_defaults.json`. During export, frame
defaults matching the repo/app defaults are omitted from the frame `.w4gl`; only
overrides remain.

You can promote shared app-level overrides into the repo default file with:
```
gorak defaults flatten
```

### Exporting an application

Export every component in one OpenROAD application:
```
gorak app export \
  --vnode myvnode \
  --database exampledb \
  application
```

Inside a Gorak project this writes `application/app.json`,
`.openroad/application/application.xml`, `application/*.w4gl`, and
`application/*.wml` for frames. The exported `app.json` contains the starting
component, description, and included applications from the source export. The
application name is implied by the folder name.

Outside a project, pass an output directory:
```
gorak app export \
  --vnode myvnode \
  --database exampledb \
  --output ./backup \
  application
```

Outside a project this writes `backup/application/app.json`,
`backup/.openroad/application/application.xml`, `backup/application/*.w4gl`, and
frame `backup/application/*.wml` files.

### Exporting a component

You can ask a Windows OpenROAD development host to export one component, then
download and encode it into the local source tree:
```
gorak component export \
  --user test \
  --host WINDOWS-PC \
  --gorak-root 'C:\Development\gorak' \
  --vnode vnode \
  --database database \
  application \
  component
```

Inside a Gorak project this writes `.openroad/application/component.xml`,
`application/component.w4gl`, and `application/component.wml` for frames. Outside
a project, pass `--output component.w4gl` to write the encoded source to an
explicit path.

The Windows-side SSH helper files are packaged with `gorak` and installed to
the remote host with `gorak remote install`.

### Generating a project summary for llm assisted development

If you pair program with an AI like ChatGPT or Grok, or you just want a markdown summary of the codebase - a file containing the main codebase as markdown code snippets can be obtained by running the following:

```
utils/llm_summary.sh
```

The file will be written to `.llm/summary.md`

---

## About the project

We are attempting to bring the Actian OpenROAD programming language into a good editor (vscode) to support things like git / vscode extensions / AI editing etc.

There are a multitude of problems with this however...

1) OpenROAD has lots of parts that are not in simple text / script form
- frame definitions
- field scripts
- metadata (return values, who has the component locked etc)

2) The source code is stored in the database
- I can't point vscode at a directory and say "Here is my OpenROAD project!"
- Editing a script in OpenROAD calls an external editor + a temp filename e.g something like: "textpad8 e0123123.w4l"
- You edit the script and press save, when OpenROAD ide detects the code editor is no longer running it reuploads the script

3) No syntax highlighting or language server exists for OpenROAD

4) It's supposed to be a multi-user environment
- Multiple developers connect to 1 database
- Opening a frame for development *locks* (logical not transactional) the component until you save and close

5) The compiler operates on the database level
- The ide compiles and runs on top of an Actian Ingres database
- cli compiler exists but is clunky

6) An OpenROAD source database consists of many "applications"
- each have their own meta props (starting component, starting database etc.)
- each consists of many components
- each has "included" applications, a list of applications whose components can be referenced

7) Some components like userclasses for example are comprised of lots of metadata that is important to edit but not available in script form.

8) OpenROAD isn't open source (boo)

---

To cross these hurdles, we are building the `gorak` compiler.

`gorak` transforms the traditional source_db -> applications -> components model and transforms it into something like this:
```
source_repo
├── gorak.json
├── field_defaults.json
├── app1
│   ├── app.json
│   ├── fm_example_frame.w4gl
│   └── fm_example_frame.wml
├── app2
│   ├── app.json
│   └── uc_example.w4gl
└── .openroad
    ├── app1
    │   └── fm_example_frame.xml
    └── app2
        └── uc_example.xml
```

### Enter `gorak`

- `gorak` is a "compiler" that transpiles a bespoke dialect of OpenROAD
  (represented in `.w4gl` and `.wml` files) to the Ingres OpenROAD based source
  database via OpenROAD `.xml` imports
- `gorak` can also transpile an OpenROAD `.xml` export file into `.w4gl` and
  `.wml` files
- in fact `gorak` can export an entire OpenROAD source database into a flat file syntax that is:
    - easily modifiable with modern development tools
    - plaintext / readable file formats
    - compatible with git
- `gorak` has a watch mode that can automatically merge disk based changes -> back into the source database for (actual) compilation by the OpenROAD compiler
    - effectively making the source database a build artifact server
- `gorak`'s watch mode also listens out for changes to the ingres database, and propagates changes back to disk (2 way sync)
    - allowing you to continue to use workbench for frame design, debugging, generation tools etc.
- `gorak` becomes the authoritative source of the code, and seamlessly manages the obnoxious workbench limitations as best is possible

Well... That's not quite true... Because import/sync has not been built yet.

`gorak` is a work in progress!

But big ambitions aside... the project's current focus is the one-way export
workflow: get useful `.w4gl`, `.wml`, and app metadata out of an OpenROAD source
database and into git-friendly files.
   
> Enable OpenROAD programmers to use VS Code and git against OpenROAD source
> without giving up Workbench yet.
