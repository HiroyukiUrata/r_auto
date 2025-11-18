import logging
import json
import re

def clean_raw_json(text: str) -> str:
    """BOMや制御文字など、JSONパースの妨げになる不要な文字を除去する"""
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = ''.join(c for c in text if c >= ' ' or c in '\n\t')
    return text

def extract_json_from_text(text: str) -> str:
    """テキストの中から ```json ... ``` または [...] のブロックを抽出する"""
    match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if match:
        logging.debug("```json ... ``` ブロックを抽出しました。")
        return match.group(1)
    
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        logging.debug("[...] ブロックを抽出しました。")
        return match.group(0)
    
    logging.warning("テキストからJSONブロックを特定できませんでした。元のテキストをそのまま使用します。")
    return text

def close_json_array_if_needed(text: str) -> str:
    """文字列が `[` で始まり `]` で終わっていない場合に、末尾の不要なカンマを削除し、`]` を追加する。"""
    text = text.strip()
    if text.startswith('[') and not text.endswith(']'):
        text_stripped_right = text.rstrip()
        if text_stripped_right.endswith(','):
            text = text_stripped_right[:-1]
            logging.debug("JSON配列の末尾にある不要なカンマを削除しました。")
        logging.debug("JSON配列が閉じていなかったため、末尾に ']' を追加します。")
        return text + ']'
    return text

def extract_complete_json_objects(text: str) -> list[dict]:
    """不完全なJSON配列文字列から、正しく閉じられているオブジェクトだけを抽出する。"""
    text = text.strip()
    if text.startswith('['):
        text = text[1:]
    parts = filter(None, text.split('{'))
    complete_objects = []
    for part in parts:
        potential_json_str = '{' + part
        open_braces = potential_json_str.count('{')
        close_braces = potential_json_str.count('}')
        if open_braces == close_braces and open_braces > 0:
            try:
                complete_objects.append(json.loads(potential_json_str.strip().rstrip(',')))
            except json.JSONDecodeError: continue
    logging.info(f"不完全なJSONから {len(complete_objects)} 件のオブジェクトを抽出しました。")
    return complete_objects

def parse_json_with_rescue(json_string: str) -> list[dict] | dict | None:
    """
    JSON文字列をパースする。失敗した場合は複数の救済処理を試みる。
    """
    try:
        json_part_str = extract_json_from_text(json_string)
        cleaned_str = clean_raw_json(json_part_str)
        return json.loads(cleaned_str)
    except json.JSONDecodeError as e1:
        logging.warning(f"最初のJSONパースに失敗: {e1}。救済処理を試みます。")
        try:
            closed_str = close_json_array_if_needed(cleaned_str)
            return json.loads(closed_str)
        except json.JSONDecodeError as e2:
            logging.warning(f"閉じ括弧の補完でもパース失敗: {e2}。最終救済処理を実行します。")
            return extract_complete_json_objects(cleaned_str)