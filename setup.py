from setuptools import setup, find_packages

setup(
    name="sshConnectionManager",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        'cryptography>=41.0.0',
        'paramiko>=3.3.1',
        'psycopg2-binary>=2.9.9',
    ],
    extras_require={
        'windows': ['windows-curses'],
        'mssql': ['pyodbc>=4.0.39'],
    },
    entry_points={
        'console_scripts': [
            'sshManager=sshmanager.ssh_manager:main_cli',
        ],
    },
)
