import multiprocessing
import os
import subprocess
from typing import List
from datetime import datetime
from recibundler.schema.reciperow import isodate_from_recipe
import json
from concurrent.futures import ThreadPoolExecutor
import string
import functools
from jsonschema import validate
from tempfile import TemporaryFile
import logging as log

log.basicConfig(level=os.environ.get("LOGLEVEL", "WARN"))


PROJECT_ROOT = "../.."
RECIPE_DIR = "../../data/recipes"
SCHEMA_DIR = "../../data/schemas"

HUGO_RECIPE_DIR = "../../content/recipes"
MAX_WORKERS = 10


def create_hugo_content_from_json(jsonfiles: List[str], clean=True):
    if clean:
        result = subprocess.run(
                ["./build_recipes.sh"],
                cwd=PROJECT_ROOT,
                shell=True,
                capture_output=True
            )
        if result.returncode != 0:
                log.error(f'Error! {result.stderr} {result.stdout}')
    
    for file in jsonfiles:  
        validate_file_name(file)
        if not clean:
            subprocess.run(["hugo", "new", "--kind", "recipes", f'''recipes/{file.replace("'", "ʼ").replace('json', 'md')}'''],
                cwd=PROJECT_ROOT )

        with open(os.path.join(RECIPE_DIR, file)) as fh:
            log.debug(f"Validating schema for {file}...")
            # validate_file_schema(fh)
        json_name = file.replace("'", "ʼ")
        mkdown_name = camel_to_snake_case(json_name).replace(".json", ".md")
        post_build_mods(
            os.path.join(RECIPE_DIR, json_name), f"{HUGO_RECIPE_DIR}/{mkdown_name}"
        )

def build():
    """
    build takes all json files in data/recipes and builds them into content pages.
    """
    clean()
    create_hugo_content_from_json([file for file in os.listdir(RECIPE_DIR)])


def clean():
    for file in os.listdir(f"{HUGO_RECIPE_DIR}"):
        log.debug(f'clean: deleting file {file}')
        os.remove(f"{HUGO_RECIPE_DIR}/{file}")


def validate_file_name(name):
    if not name.endswith(".json"):
        raise Exception("name must be .json extension")
    return name


def validate_file_schema(fh):
    instance = json.loads(fh.read())
    schema = get_recipe_schema()
    try:
        validate(instance=instance, schema=schema)
    except Exception as e:
        log.debug(f"Not valid! {e}")
        raise e


@functools.lru_cache
def get_recipe_schema():
    with open(f"{SCHEMA_DIR}/recipes.json") as fh:
        j = json.loads(fh.read())
    return j


def camel_to_snake_case(name: str) -> str:
    return "".join(
        [name[0].lower()]
        + [
            c
            if (c not in string.ascii_letters or c.islower()) or c in ".()"
            else f"-{c.lower()}"
            for c in name[1:]
        ]
    )


# POST BUILD SCRIPTS #
"""
Because content (content/recipes) is generated from scratch each
time, additional modification to form are required.
"""


def post_build_mods(file: str, mkdown: str) -> None:
    with open(file) as fh:
        recipe = json.loads(fh.read())
    log.debug(f'post_build_mods starting. mkdown={mkdown}, file={file}')
    correct_date(recipe, os.path.join(mkdown))
    use_json_name_as_title(recipe, os.path.join(mkdown))
    correct_categories(recipe, os.path.join(mkdown))
    add_summary(recipe, os.path.join(mkdown))
    add_author(recipe, os.path.join(mkdown))
    add_photo_author(recipe, os.path.join(mkdown))
    try:
        add_frontmatter(recipe, mkdown)
    except Exception as e:
        print("ERROR", e)


def correct_date(recipe: dict, mkdown: str) -> None:
    date = datetime.strptime(recipe["timestamp"], "%m/%d/%Y %H:%M:%S")
    timestamp = date.strftime("%Y-%m-%dT%H:%M:%S-05:00")
    subprocess.run(["sed", "-i", "", f"s#.*\\$DATE\\$$#date: {timestamp}#", mkdown])


def use_json_name_as_title(recipe: dict, mkdown: str) -> None:
    log.debug(f'{__name__}: replacing name with `{recipe["name"]}` | NoConvoCooking')
    subprocess.run(
        ["sed", "-i", "", f"s#.*\\$TITLE\\$$#title: {recipe['name']}#", mkdown]
    )


def correct_categories(recipe: dict, mkdown: str) -> None:
    if "categories" not in recipe:
        return
    categories = recipe["categories"]
    subprocess.run(
        ["sed", "-i", "", f"s#.*\\$CATEGORIES\\$$#categories: {categories}#", mkdown]
    )


def add_summary(recipe: dict, mkdown: str) -> None:
    """
    Add the summary field to content as frontmatter.
    https://gohugo.io/content-management/summaries/#front-matter-summary
    """
    if "summary" not in recipe:
        return
    summary = recipe["summary"].replace('"', '\\\\"') or " "
    subprocess.run(
        ["sed", "-i", "", f's#.*\\$SUMMARY\\$$#summary: "{summary}"#', mkdown]
    )


def add_author(recipe: dict, mkdown: str) -> None:
    if "attribution" not in recipe or "name" not in recipe["attribution"]:
        return
    author = recipe["attribution"]["name"]
    subprocess.run(["sed", "-i", "", f"s#.*\\$AUTHOR\\$$#author: {author}#", mkdown])


def add_photo_author(recipe: dict, mkdown: str) -> None:
    if "photoAttribution" not in recipe:
        return
    author = recipe["photoAttribution"]["name"]
    author_link = (
        recipe["photoAttribution"]["link"]
        if "link" in recipe["photoAttribution"]
        else None
    )
    subprocess.run(["sed", "-i", "", f"s#.*\\$PHOTO_AUTHOR\\$$#photoAuthor: {author}#", mkdown])
    if author_link is not None:
        subprocess.run(["sed", "-i", "", f"s#.*\\$PHOTO_AUTHOR_LINK\\$$#photoAuthorLink: {author_link}#", mkdown])



def add_frontmatter(recipe: dict, mkdown: str) -> None:
    with TemporaryFile() as fp:
        with open(os.path.join(mkdown)) as orig:
            for line in orig:
                if line == "prepTime: 0\n" and False:
                    fp.write(
                        b"prepTime: "
                        + str(recipe.get("prepTimeMinutes", "0")).encode()
                        + b"\n"
                    )
                elif line == "cookTime: 0\n":
                    fp.write(
                        b"cookTime: "
                        + str(recipe.get("cookTimeMinutes", "0")).encode()
                        + b"\n"
                    )
                elif line == "difficulty: 0\n":
                    fp.write(
                        b"difficulty: "
                        + str(recipe.get("difficulty", "0")).encode()
                        + b"\n"
                    )
                elif line == 'featured_image: ""\n':
                    image_url = recipe.get("imageUrl", '""')
                    fp.write(f"featured_image: {image_url}\n".encode())
                elif line == 'youtube: ""\n':
                    youtube = recipe['media'][0]['comment'] if recipe.get('media') and len(recipe['media']) > 0 and 'comment' in recipe['media'][0] else '""'
                    fp.write(f"youtube: {youtube}\n".encode())
                elif line == "diets: []\n" and recipe.get("diets"):
                    fp.write(f'diets: {recipe["diets"]}\n'.encode())
                elif line == "cuisines: []\n" and recipe.get("cuisines"):
                    fp.write(f'cuisines: {recipe["cuisines"]}\n'.encode())
                elif line == "#$JSON_DATA$\n":
                    fp.write(f'jsonData: {json.dumps(recipe)}'.encode())
                else:
                    fp.write(line.encode())
            # Add all recipe data as an object
            fp.seek(0)
        with open(mkdown, mode="w") as fh:
            fh.writelines([l.decode("utf-8") for l in fp.readlines()])


if __name__ == "__main__":
    build()
