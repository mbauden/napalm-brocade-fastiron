"""setup.py file."""

import uuid

from setuptools import setup, find_packages
from pip.req import parse_requirements

__author__ = 'Matt Baudendistel <mbaudendistel@contegix.com>'

install_reqs = parse_requirements('requirements.txt', session=uuid.uuid1())
reqs = [str(ir.req) for ir in install_reqs]

setup(
    name="napalm-brocade-fastiron",
    version="0.1.0",
    packages=find_packages(),
    author="Matt Baudendistel",
    author_email="mbaudendistel@contegix.com",
    description="Network Automation and Programmability Abstraction Layer with Multivendor support",
    classifiers=[
        'Topic :: Utilities',
        'Programming Language :: Python',
        'Operating System :: POSIX :: Linux',
        'Operating System :: MacOS',
    ],
    url="https://github.com/napalm-automation/napalm-skeleton",
    include_package_data=True,
    install_requires=reqs,
)
