from setuptools import setup, find_packages

setup(
    name="sshConnectionManager",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        'cryptography',
        'pyodbc',  # for MSSQL
        'psycopg2-binary',  # for PostgreSQL
    ],
    entry_points={
        'console_scripts': [
            'sshManager=sshmanager.ssh_manager:main_cli',
        ],
    },
)
