from setuptools import setup, find_packages


setup(
    name='mkdocs-juvix-plugin',
    version='0.1.3',
    description='A plugin to render Juvix code blocks in MkDocs.',
    long_description='',
    keywords='mkdocs',
    # url='https//github.com/anoma/juvix-mkdocs/',
    author='Jonathan Prieto-Cubides',
    author_email='jonathan.cubides@uib.no',
    license='MIT',
    python_requires='>=3.11',
    install_requires=[
        'mkdocs >= 1.5.0',
    ],
    classifiers=[
        'Intended Audience :: Developers',
        'Intended Audience :: Information Technology',
        'Programming Language :: Python',
    ],
    packages=find_packages(),
    entry_points={
        'mkdocs.plugins': [
            'juvix = mkdocs_juvix.plugin:JuvixPlugin',
            'juvix-standalone = mkdocs_juvix.standalone:render'
        ]
    }
)
