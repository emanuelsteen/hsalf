from setuptools import setup
name = 'hsalf'
setup(
    name=name,
    version='0.0.1',
    author='Nam T. Nguyen',
    author_email='namn@bluemoon.com.vn',
    url='https://bitbucket.org/namn/hsalf/overview',
    description='Hsalf is a pure Python library to read and write Flash files (SWF).',
    long_description='Hsalf is a pure Python library to read and write Flash files (SWF).',
    platforms='Any',
    package_dir={'':'.'},
    packages=['hsalf'],
    package_data={'': ['README', 'LICENSE']},
    license='MIT',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Multimedia',
        'Topic :: Security',
        'Topic :: Software Development :: Assemblers',
        'Topic :: Software Development :: Disassemblers',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ]
)
