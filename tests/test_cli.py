# tests/test_cli.py
import sys
import pytest
from unittest.mock import patch
from tiny_harness.cli import parse_args


def test_parse_args_one_shot():
    with patch.object(sys, 'argv', ['tiny-harness', 'Hello']):
        args = parse_args()
        assert args.prompt == 'Hello'


def test_parse_args_no_prompt():
    with patch.object(sys, 'argv', ['tiny-harness']):
        args = parse_args()
        assert args.prompt is None


def test_parse_args_with_options():
    with patch.object(sys, 'argv', [
        'tiny-harness', 'Hello',
        '--model', 'claude-opus',
        '--workspace', '/tmp/project',
        '--max-iterations', '10',
        '--skills', 'files',
    ]):
        args = parse_args()
        assert args.prompt == 'Hello'
        assert args.model == 'claude-opus'
        assert args.workspace == '/tmp/project'
        assert args.max_iterations == 10
        assert args.skills == 'files'
        assert args.provider == 'anthropic'
        assert args.api_base_url is None


def test_parse_args_with_provider():
    with patch.object(sys, 'argv', ['tiny-harness', 'hi', '--provider', 'deepseek', '--api-base-url', 'https://api.deepseek.com/v1']):
        args = parse_args()
        assert args.provider == 'deepseek'
        assert args.api_base_url == 'https://api.deepseek.com/v1'
