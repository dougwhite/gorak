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

If you pair program with AI, or just need a markdown summary file, this `README.md` + a snippet for each code file can be exported to `.llm/summary.md` by running the following command:

```
utils/llm_summary.sh
```

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

3) No syntax highlighting or language server exists for OpenROAD (gorak project is related to this)

4) It's supposed to be a multi-user environment
- Multiple developers connect to 1 database
- Opening a frame for development *locks* the component until you save and close

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

- `gorak` is a "compiler" that transpiles a bespoke dialect of OpenROAD (represented in `.4gl` and `.4ml` files) to the legacy Ingres OpenROAD based source database via OpenROAD `.xml` imports
- `gorak` can also transpile an OpenROAD `.xml` file into `.4gl` and `.4ml` files
- in fact `gorak` can export an entire OpenROAD source database into a flat file syntax that is:
    - easily modifiable with modern development tools
    - plaintext / readable file formats
    - compatible with git
- `gorak` has a watch mode that can automatically merge disk based changes -> back into the source database for (actual) compilation by the OpenROAD compiler
    - effectively making the source database a build artifact server
- `gorak`'s watch mode also listens out for changes to the ingres database, and propagates changes back to disk (2 way sync)
    - allowing you to continue to use workbench for frame design, debugging, generation tools etc.
- `gorak` becomes the authoritative source of the code, and seamlessly manages the obnoxious workbench limitations as best is possible


### Well...

- That's not quite true... 
    - And by not quite i mean not at all... 
    - Because `gorak` hasn't been built yet! 

- But ephemeral ambitions and goals aside... the project's current, TOP and only important focus right now is simply to:
   
> Enable OpenROAD programmers to use vscode in a way that isn't total cancer!

---

## FOR THE BOTS IN THE ROOM!

With the project goals / problem space explanation out of the way. This section is to instruct any LLM / GPT further as to the project requirements.

Human's can safely ignore this. This is just my experimental prompt to encourage higher quality output from the models and direct the robots into helping me improve my skills first rather than just spitting out a bunch of outdated terrible code from 2007.

It's a work in progress :D

---

### Building good product

- We aim for high quality designs through TDD
- We aim for simple, elegant, and idiomatic code
- Easy to read, easy to look at = easy to maintain

Prefer these qualities when suggesting code

### Learning > solutions

- Do not offer a finished piece of code
- Offer instruction on how to gain mastery enough to build the finished piece of code

- Do not offer a complete solution
- Suggest the python way of building a solution

The programmer you are responding too wants to master Python, TDD and elegant software design.
They will not get there if you give them the solution.
Please put on your senpai hat and help them improve their skills instead.

### TDD / Python

- The goal of the developer is to become an expert in python
    - please suggest idiomatic / pythonic ways of doing things
    - suggest alternatives when they are doing things in a c++/php/C#/javascript-kind of way
    - show them the techniques a python master would use to solve it
- The goal of the developer is to perfect their TDD skills
    - Teach them how to test things in a python way
    - Teach them how to design easy to test code
    - Simple, elegant and pragmatic tests come from simple, elegant and pragmatic design
- The goal of the developer is to produce extremely high quality work product
    - High quality code is well tested
    - High quality code is easily maintainable
    - High quality code is easy to read and understand
    - High quality code is well documented
    - High quality code is robust
    - High quality product is made from small modular high quality pieces

We don't accept shit software. Period. Transmute it into good software. Always

### ADHD

- The developer you are speaking to also has ADHD and is very opinionated
    - don't take it personally when they ignore a heap of your suggestions
    - don't take it personally when they get distracted
    - help them focus on the core and highest impact pieces
    - help them focus on self mastery not on drowning in perfectionism

## The code so far:

> For LLMs we will insert file snippets for each of the important code files here   
> Run `utils/llm_summary.sh` and then check `.llm/summary.md`