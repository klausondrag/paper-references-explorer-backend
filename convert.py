import shutil
from pathlib import Path
import logging
import math
from typing import TextIO, Tuple
import re

from git import Repo
import nltk

nltk.download('stopwords')

logging.basicConfig(format='%(asctime)s - %(levelname)-8s - %(name)s    - %(message)s', level=logging.DEBUG)
logger = logging.getLogger(__name__)

pattern_alpha = re.compile('[^a-zA-Z ]+')
pattern_alphanumeric = re.compile('[\W]+')
stop_words = set(nltk.corpus.stopwords.words('english'))
stemmer = nltk.stem.SnowballStemmer('english')
vocab = set()


def main(source_url: str = 'https://github.com/paperscape/paperscape-data.git',
         n_max_splits: int = 7, max_elements_per_file: int = 15000,
         clean_input: bool = False, clean_output_for_blast: bool = False, clean_output_for_redis: bool = False) -> None:
    base_path = Path('data')
    input_path = base_path / 'input'
    output_path_base = base_path / 'output_for'
    output_path_blast = output_path_base / 'blast'
    output_path_redis = output_path_base / 'redis'
    n_total_elements = 0
    setup_directories(input_path, clean_input, output_path_blast, clean_output_for_blast,
                      output_path_redis, clean_output_for_redis, source_url)

    input_file_paths = input_path.glob('*.csv')
    input_file_paths = sorted(input_file_paths, reverse=True)
    for input_file_path in input_file_paths:
        logging.info(f'Converting {input_file_path.name}...')
        year = input_file_path.name[5:9]
        n_elements_in_file = count_elements_in_file(input_file_path)
        with open(str(input_file_path), 'r') as input_file:
            n_files_needed = math.ceil(n_elements_in_file / max_elements_per_file)
            n_elements_in_file = 0
            for file_index in range(n_files_needed):
                output_file_path = output_path_blast / f'{year}_{file_index + 1}.json'
                if output_file_path.exists():
                    logging.info(f'File {output_file_path.name} already exists. Skipping.')
                else:
                    n_elements_in_file += write_content(input_file, output_file_path, max_elements_per_file,
                                                        n_max_splits, year)
            logging.info(f'N elements converted: {n_elements_in_file}')
            n_total_elements += n_elements_in_file
            logging.info(f'vocab size so far: {len(vocab)}')

    logging.info(f'N elements converted in total: {n_total_elements}')
    logging.info(f'vocab size total: {len(vocab)}')


def setup_directories(input_path: Path, clean_input: bool, output_path_blast: Path, clean_output_for_blast: bool,
                      output_path_redis: Path, clean_output_for_redis: bool, source_url: str) -> None:
    clean_folder_maybe(input_path, clean_input, recreate=False)
    clean_folder_maybe(output_path_blast, clean_output_for_blast)
    clean_folder_maybe(output_path_redis, clean_output_for_redis)
    if not input_path.exists():
        logger.info('Cloning repo...')
        Repo.clone_from(source_url, input_path)
        logger.info('Finished cloning repo')


def clean_folder_maybe(path: Path, clean_folder: bool, recreate: bool = True) -> None:
    if clean_folder and path.exists():
        logger.info(f'Cleaning folder {path.name}')
        shutil.rmtree(path)

    if recreate:
        path.mkdir(exist_ok=True, parents=True)


def count_elements_in_file(input_file_path: Path) -> int:
    n_elements_in_file = 0
    with open(str(input_file_path), 'r') as input_file:
        for line in input_file:
            line_clean = line.strip()
            if not line_clean.startswith('#'):
                n_elements_in_file += 1
    return n_elements_in_file


def write_content(input_file: TextIO, output_file_path: Path, max_elements_per_file: int,
                  n_max_splits: int, year: str) -> int:
    with open(str(output_file_path), 'w') as output_file:
        output_file.write('[')
        n_elements = 0
        is_first_line = True
        for line in input_file:
            line_clean = line.strip()
            if not line_clean.startswith('#'):
                n_elements += 1
                arxiv_id, authors, title = extract_blast_fields(line, n_max_splits)
                document = convert_to_json_string(year, is_first_line, arxiv_id, authors, title)
                output_file.write(document)
                is_first_line = False
                if n_elements == max_elements_per_file:
                    break
        output_file.write('\n]')
        return n_elements


def convert_to_json_string(year: str, is_first_line: bool, arxiv_id: str, authors: str, title: str) -> str:
    document = f"""{'' if is_first_line else ','}
  {{
    "type": "PUT",
    "document": {{
      "id": "{arxiv_id}",
      "fields": {{
        "year": "{year}",
        "authors": "{authors}",
        "title": "{title}"
      }}
    }}
  }}"""
    return document


def extract_blast_fields(line: str, n_max_splits: int) -> Tuple[str, str, str]:
    fields = line.split(';', n_max_splits)
    arxiv_id = clean_id(fields[0])
    authors = clean_authors(fields[5])
    title = clean_title(fields[-1])
    return arxiv_id, authors, title


def clean_field(s: str) -> str:
    return s.replace('"', '').replace('\t', ' ').replace('\\', '\\\\')


def clean_id(s: str) -> str:
    s = clean_field(s)
    s = pattern_alphanumeric.sub('_', s)
    return s


def clean_authors(s: str) -> str:
    s = clean_field(s)
    s = s.lower()
    s = [w.strip().split('.')[-1]
         for w in s.split(',')]
    s = [pattern_alpha.sub(' ', w) for w in s]
    [vocab.add(w) for w in s]
    s = ' '.join(s)
    return s


def clean_title(s: str) -> str:
    s = clean_field(s)
    s = s.lower()
    s = pattern_alpha.sub(' ', s)
    s = [stemmer.stem(w)
         for w in s.split()
         if w not in stop_words and len(w) > 3]
    [vocab.add(w) for w in s]
    s = ' '.join(s)
    return s


if __name__ == '__main__':
    main()
