import setuptools

setuptools.setup(
    name='geoprofile',
    version='0.1',
    description='Raster and vector files profiling service',
    license='MIT',
    packages=setuptools.find_packages(),
    install_requires=[
        # moved to requirements.txt
    ],
    package_data={'geoprofile': ['logging.conf']},
    python_requires='>=3.7',
    zip_safe=False,
)
