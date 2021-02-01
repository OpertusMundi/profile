import setuptools

setuptools.setup(
    name='geoprofile',
    version='1.0.0',
    description='Raster and vector files profiling service',
    license='MIT',
    packages=setuptools.find_packages(exclude=('tests*',)),
    install_requires=[
        # moved to requirements.txt
    ],
    package_data={'geoprofile': [
        'logging.conf', 'schema.sql'
    ]},
    python_requires='>=3.7',
    zip_safe=False,
)
