#!/usr/bin/python
import ez_setup
ez_setup.use_setuptools(version='0.6c6')
from setuptools import setup
import sys, os.path

setup(
    name='audiomangler',
    version='0.1',
    description='audio file transcoder, renamer, etc',
    author='Andrew Mahone',
    author_email='andrew.mahone@gmail.com',
    packages=['audiomangler'],
    package_dir={'audiomangler': 'audiomangler'},
    install_requires='''
        pyparsing >= 1.4.11
        mutagen >= 1.13
    ''',
    entry_points={
        'console_scripts': [
            'am_rename = audiomangler.cli:rename',
            'am_sync = audiomangler.cli:sync',
            'am_transcode = audiomangler.cli:sync',
            'am_replaygain = audiomangler.cli:replaygain',
        ]
    },
)
