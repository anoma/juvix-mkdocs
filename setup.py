from setuptools import find_packages, setup

setup(
    name="mkdocs-juvix-plugin",
    version="0.2.5",
    description="A plugin to render Juvix code blocks in MkDocs.",
    long_description="",
    keywords="mkdocs",
    author="Jonathan Prieto-Cubides, and GitHub contributors",
    author_email="jonathan@heliax.dev",
    license="MIT",
    python_requires=">=3.9",
    install_requires=["mkdocs >= 1.5.0", "pyYaml", "pymdown-extensions"],
    classifiers=[
        "Intended Audience :: Developers",
        "Intended Audience :: Information Technology",
        "Programming Language :: Python",
    ],
    packages=find_packages(),
    entry_points={
        "mkdocs.plugins": [
            "juvix = mkdocs_juvix.plugin:JuvixPlugin",
            "juvix-standalone = mkdocs_juvix.standalone:render",
        ]
    },
)
