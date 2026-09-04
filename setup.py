import setuptools

with open('README.rst', 'r') as f:
    long_description = f.read()

with open('schwab/version.py', 'r') as f:
    '''Version looks like `version = '1.2.3'`'''
    version = [s.strip() for s in f.read().strip().split('=')][1]
    version = version[1:-1]

setuptools.setup(
    name='schwab-py',
    version=version,
    author='Alex Golec',
    author_email='bottomless.septic.tank@gmail.com',
    description='Unofficial API wrapper for the Schwab HTTP API',
    long_description=long_description,
    long_description_content_type='text/x-rst',
    url='https://github.com/alexgolec/schwab-py',
    packages=setuptools.find_packages(exclude=('tests', 'tests.*')),
    classifiers=[
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'Programming Language :: Python :: 3.14',
        'Operating System :: OS Independent',
        'Intended Audience :: Developers',
        'Development Status :: 4 - Beta',
        'Natural Language :: English',
        'Topic :: Office/Business :: Financial :: Investment',
    ],
    python_requires='>=3.12',
    install_requires=[
        'autopep8>=2.3.2',
        'authlib>=1.8.0',
        'certifi>=2026.7.22',
        'flask>=3.1.3',
        'httpx2>=2.12.0',
        'multiprocess>=0.70.19',
        'psutil>=7.2.2',
        'python-dateutil>=2.9.0.post0',
        'urllib3>=2.7.0',
        'websockets>=17.1'
    ],
    extras_require={
        'dev': [
            'callee',
            'colorama',
            'coverage',
            'build',
            'pytest',
            'pytz',
            'setuptools',
            'sphinx_rtd_theme',
            'twine',
            'tox',
            'wheel',
        ]
    },
    keywords='finance trading equities bonds options research',
    project_urls={
        'Documentation': 'https://schwab-py.readthedocs.io/en/latest/',
        'Source': 'https://github.com/alexgolec/schwab-py',
        'Tracker': 'https://github.com/alexgolec/schwab-py/issues',
    },
    license='MIT',
    scripts=[
        'bin/schwab-order-codegen.py',
        'bin/schwab-generate-token.py',
    ],
)

