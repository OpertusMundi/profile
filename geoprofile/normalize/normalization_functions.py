import re
from datetime import datetime
from typing import List, Union
from nltk import word_tokenize
from polyglot.text import Text
from polyglot.downloader import downloader
from transliterate import translit, get_available_language_codes

DATE_FORMATS: List[str] = ['%Y-%m-%d %H:%M:%S%Z', '%Y-%m-%d %H:%M:%S',
                           '%m-%d-%y %H:%M:%S', '%m-%d-%y %H:%M:%S%Z',
                           '%Y-%m-%d', '%d %m-%Y', '%Y/%b/%d', '%d-%m-%Y', '%d-%b-%Y', '%d/%m/%Y', '%d %b %Y']


IDENTIFIER_MAX_LENGTH = 63

SYSTEM_TABLE_NAMES = ["spatial_ref_sys", "geography_columns", "geometry_columns", "raster_columns", "raster_overviews",
                      "cdb_tablemetadata", "geometry", "raster"]

RESERVED_TABLE_NAMES = ["layergroup", "all", "public"]

RESERVED_COLUMN_NAMES = ["tableoid", "xmin", "cmin", "xmax", "cmax", "ctid"]


if downloader.status("TASK:transliteration2") != 'installed':
    downloader.download("TASK:transliteration2", quiet=True)


def date_normalization(date_string: str, target_format: str = '%d/%m/%Y'):
    if date_string:
        for temp_format in DATE_FORMATS:
            try:
                transformed_date = datetime.strptime(date_string, temp_format).strftime(target_format)
            except ValueError:
                pass
            else:
                return transformed_date
    return date_string


def phone_normalization(number_string: str, exit_code_digits: str = ''):
    phone_numbers = []
    if ',' in number_string:
        phone_numbers = number_string.split(',')
    else:
        phone_numbers.append(number_string)
    return ', '.join([normalize_single_phone_number(number, exit_code_digits) for number in phone_numbers])


def normalize_single_phone_number(number_string: str, exit_code_digits: str):
    normalized_phone = number_string
    if normalized_phone.startswith("00"):
        normalized_phone = normalized_phone[2:]
    return exit_code_digits + re.sub('[^0-9]', '', normalized_phone)


def special_character_normalization(literal: str):
    if literal:
        return re.sub('[^A-Za-z0-9]+', ' ', literal)
    return ""


def alphabetical_normalization(literal: str):
    if not literal:
        return ""
    parts: List[str] = word_tokenize(literal)
    sorted_parts: List[str] = sorted(parts, key=str.casefold)
    normalized_literal: str = ""
    for part in sorted_parts:
        normalized_literal += part + " "
    normalized_literal = normalized_literal.strip()
    return normalized_literal


def case_normalization(literal: str):
    if not literal:
        return ""
    return literal.lower()


def transliteration_slow(blob: str, target_lang: str = "la"):
    try:
        text = Text(blob)
        transliterated_words: List[str] = text.transliterate(target_lang)
    except ValueError:
        # Language not supported
        return blob
    else:
        return ' '.join(transliterated_words)


def transliteration(blob: str, source_langs: Union[List[str], str], target_lang: str = "la"):
    if blob is None:
        return None
    text: str = blob
    available_langs = get_available_language_codes()
    if isinstance(source_langs, str):
        source_langs = [source_langs]
    for lang in source_langs:
        if lang in available_langs:
            text = translit(text, lang, reversed=True)
        else:
            text = transliteration_slow(blob, target_lang)
    return text


def value_cleaning(literal: str):
    output = re.sub('\\s+', '', literal)  # remove white space
    output = re.sub('\"', '\'', output)  # change double to single quotes
    output = re.sub('\\|', ';', output)  # change csv delimiter from | to ;
    output = re.sub('(\r\n|\r|\n)', ' ', output)  # replace tabs and newlines with space
    output = re.sub('\\\\', '/', output)  # change // to \ for urls
    output = re.sub('[^a-zA-ZA-Za-zΑ-Ωα-ωίϊΐόάέύϋΰήώ0-9-._~:/?#@!$ &038;\'()*+,=]', '', output)  # remove invalid url characters
    return output


def column_name_normalization(column_names: List[str], version: int = 2):
    # Based on https://carto.com/developers/import-api/guides/column-names-normalization/
    # https://github.com/CartoDB/cartodb/blob/f9e43b9f8ce67925cce3efa191f257c3c0ff8962/services/importer/lib/importer/column.rb
    normalized_column_names = []
    for candidate_column_name in column_names:
        existing_names: List[str] = [name for name in column_names if name != candidate_column_name]
        if version == 1:
            reserved_words = []
            column_name = candidate_column_name
            if not column_name:
                column_name = 'untitled_column'
            column_name = ' '.join(column_name.split())
            column_name = re.sub('_{2,}', '_', re.sub('[^a-z0-9]', '_', column_name))
            if re.match('^[a-z_]', column_name):
                column_name = f'column_{column_name}'
            column_name = avoid_collisions(column_name, existing_names, reserved_words)
        elif version == 2:
            new_column_name = re.sub('_{2,}', '_', sanitize_name(candidate_column_name))[0:IDENTIFIER_MAX_LENGTH]
            column_name = avoid_collisions(new_column_name, existing_names, RESERVED_COLUMN_NAMES)
        elif version == 3:
            new_column_name = sanitize_name(candidate_column_name).replace('-', '_')[0:IDENTIFIER_MAX_LENGTH]
            column_name = avoid_collisions(new_column_name, existing_names, RESERVED_COLUMN_NAMES)
        else:
            column_name = candidate_column_name
        normalized_column_names.append(column_name)
    return normalized_column_names


def reserved_or_unsupported(column_name: str):
    if column_name.lower() in RESERVED_COLUMN_NAMES or re.match('^[a-zA-Z_]', column_name):
        return True
    return False


def sanitize_name(column_name: str):
    name = transliteration(column_name, get_available_language_codes())
    if reserved_or_unsupported(name):
        return f"_{name}"
    return name


def avoid_collisions(name: str, existing_names: List[str], reserved_words: List[str], max_length=IDENTIFIER_MAX_LENGTH):
    cnt = 1
    new_name: str = name
    while new_name in existing_names or new_name.lower() in reserved_words:
        suffix = f"_{cnt}"
        new_name = name[0:max_length-len(suffix)] + suffix
        cnt += 1
    return new_name
