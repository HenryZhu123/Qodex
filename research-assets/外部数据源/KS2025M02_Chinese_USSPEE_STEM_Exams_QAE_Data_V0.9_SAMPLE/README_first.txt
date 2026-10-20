Corpus Title: Chinese USSPEE STEM Exams QAE Data - V0.9 SAMPLE
Keensight Catalog ID: KS2025M02
Date: July 2, 2025 

1.0 Overview

This dataset offers a comprehensive collection of Question, Answer, Explanation
(QAE) triplets drawn from China's University-Specific Exams of the Postgraduate
Entrance Exam (USSPEE,研究生入学考试招生单位自命题科目), the standardized
national assessment required for admission to master's degree programs across
China.


2.0 Contents

This package has the following content and structure:

./data -- directory containing exam data

This directory has 6 subdirectories, each containing data for an individual
exam. Directories are named like USSPEE-STEM_exam_dddd where "dddd" is a
zero-padded, four digit integer.

Each individual ./data/USSPEE-STEM_exam_dddd subdirectory contains the
following exam materials:

./USSPEE-STEM_exam_dddd.json -- exam data in json format, where "dddd" matches
                                the integer string of the parent directory 

./USSPEE-STEM_exam_dddd.md -- exam data in markdown format, where "dddd"
                              matches the integer string of the parent
                              directory 

./images -- directory containing any image files referenced in the exam data,
            in jpg format

./docs -- directory containing documentation files
./docs/files.md5 -- file containing md5 checksums for each file in the package

./README_first.txt -- this file, meant to provide basic information about this
                      corpus

./README_main.pdf -- main README file, with detailed information about this
                     corpus


3.0 Corpus Details

For detailed information about this corpus, see the main README file for 
this package, located here: ./README_main.pdf


4.0 Copyright Information

    © 2025 Keensight LLC


5.0 Contact Information

For further information about this dataset, contact the following
contributors:

   Dr. Xiaoyi Ma <xma@keensight.ai> -- Keensight Founder/CEO

----
README created by Kira Griffitt on July 2, 2025
       updated by Kira Griffitt on July 2, 2025
