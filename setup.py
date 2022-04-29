import setuptools

with open('requirements.txt', 'r') as fh:
    requirements = fh.read()

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name='pyta',
    version='0.0.1',
    author='Wojtek Pudelko',
    author_email='wojciech.pudelko@psi.ch',
    description='My pyta, have fun',
    long_description=long_description,
    long_description_content_type='text/markdown',
    packages=setuptools.find_packages(),
    python_requires=">=3.7",
    install_requires=requirements,
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    include_package_data=True,
    entry_points={
        'console_scripts': [
            'pyta2d = main:open2D',
            'pyta3d = main:open3D',
            'h5_to_pickle = main:pickle_h5',
            'reshape_pickled = main:reshape_pickled',
            'db = main:db'
        ],
    }
)