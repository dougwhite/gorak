# `gorak` 

For developers who enjoy OpenROAD and their hair.

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

## CLI helpers

### Trying out the util

You can run the tool against the example .xml fixture (or your own OpenROAD `.xml` export)
```
uv run gorak tests/fixtures/fm_example_frame.xml
```

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
├── app1
│   ├── .openroad
│   │    └── fm_example_frame.xml
│   ├── fm_example_frame.4gl
│   └── fm_example_frame.4ml
└── app2
    ├── .openroad
    │    └── uc_example.xml
    └── uc_example.4gl
```

### Enter `gorak`

- `gorak` is a "compiler" that transpiles a bespoke dialect of OpenROAD (represented in `.4gl` and `.4ml` files) to the Ingres OpenROAD based source database via OpenROAD `.xml` imports
- `gorak` can also transpile an OpenROAD `.xml` export file into `.4gl` and `.4ml` files
- in fact `gorak` can export an entire OpenROAD source database into a flat file syntax that is:
    - easily modifiable with modern development tools
    - plaintext / readable file formats
    - compatible with git
- `gorak` has a watch mode that can automatically merge disk based changes -> back into the source database for (actual) compilation by the OpenROAD compiler
    - effectively making the source database a build artifact server
- `gorak`'s watch mode also listens out for changes to the ingres database, and propagates changes back to disk (2 way sync)
    - allowing you to continue to use workbench for frame design, debugging, generation tools etc.
- `gorak` becomes the authoritative source of the code, and seamlessly manages the obnoxious workbench limitations as best is possible

Well... That's not quite true... Because `gorak` hasn't been built yet! 

`gorak` is a work in progress!

But big ambitions aside... the project's current, TOP and only important focus right now is simply to:
   
> Enable OpenROAD programmers to use vscode in a way that isn't total cancer!