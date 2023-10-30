#!/bin/bash

rm -rf dist
python3.11 setup.py bdist_wheel sdist --formats gztar && twine upload dist/*
