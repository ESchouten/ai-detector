# Public ear-tag software and checkpoint check

Bounded primary-source check on 3 October 2026. No new model was downloaded or
executed. This is a checked shortlist, not proof that no other release exists.

| Source | What is actually public | Relevant limitation |
| --- | --- | --- |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) | Maintained OCR library and hosted PaddleOCR-derived models; our existing research uses the pinned 3.9.2 release and verified weights. | Generic text detection/recognition; not a cow ear-tag locator or tag-to-animal ownership model. The existing fixed cattle-crop tests remain the relevant evidence. |
| [Microsoft TrOCR small printed](https://huggingface.co/microsoft/trocr-small-printed) | Official downloadable model and Transformers implementation. | Intended for a single text-line image and trained on document text. It needs localization/rectification; our separate adapted-reader tests already cover this candidate. |
| [Cattle-ID-Scanner](https://github.com/LogicHarvest/Cattle-ID-Scanner/tree/5ed0eb90eade2e94915e69ccb03bc0b2c4fc87e1) | Seven-file repository, including a 70-line Tesseract preprocessing/regex script. Checked revision `5ed0eb90eade2e94915e69ccb03bc0b2c4fc87e1`. | No trained tag-detector weights, cattle-specific OCR checkpoint or animal ownership logic. Numeric substrings are concatenated, which would lose distinctions our literal-reader evaluation preserves. |
| [Wageningen live-stream study](https://www.frontiersin.org/journals/animal-science/articles/10.3389/fanim.2022.846893/full) | Paper with camera-specific yellow-tag preprocessing and a retrained digit recognizer. | Its public implementation link is the generic street-number model below; I did not verify a released cattle-adapted checkpoint. Reported live precision/sensitivity must not be treated as our camera performance. |
| [SVHNClassifier-PyTorch](https://github.com/potterhsu/SVHNClassifier-PyTorch/tree/5f062e5afc134d9b56ab3dc6282e7762799f5159) | Code at revision `5f062e5afc134d9b56ab3dc6282e7762799f5159`, plus a README link to `model-54000.pth`. | These are street-number weights, not the Wageningen cattle adaptation. The [linked Drive endpoint](https://drive.google.com/open?id=1DSg3F5GpouEvU9n7YSPdUKH1CSmkdwSw) could not be fetched during this check, so current binary availability was not verified. |
| [ReadMyCow, WACV 2024](https://openaccess.thecvf.com/content/WACV2024/papers/Smink_Computer_Vision_on_the_Edge_Individual_Cattle_Identification_in_Real-Time_WACV_2024_paper.pdf) | Author paper describing specialized detection, tracking, selection of readable frames and recognition. | The checked author/paper paths did not expose a usable author-trained checkpoint or installable package. This remains a useful method reference rather than an available replacement model. |
| [Gao et al., Sensors 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC11014036/) | Paper and author datasets used by the current bounded localization/reader pilots. | Checked release paths provide data; a downloadable author-trained Small-YOLOv5/CRNN checkpoint was not verified. |
| [Smart-glasses ear-tag study, author publication page](https://ohyoungwoo.com/publications/#livestock-eartag-recognition-system-based-on-smart-glasses-and-lightweight-ocr) | Author abstract and citation for a 2021 lightweight OCR system. | The page has no linked model/code release; its reported result is not evidence of an available pretrained model. |

The practical reusable components are therefore the generic pretrained OCR
libraries already under test. The missing evidence is still three separate
things: finding a tag in a full frame, reading its literal number, and attaching
that reading to the correct current animal. A package advertised as an ear-tag
scanner does not establish all three. No new generic OCR model grid is justified
by this search. The printing on the physical reverse side is a separate
manufacturer/tag-format question, not something these libraries can infer from
an unreadable or unprinted surface.
