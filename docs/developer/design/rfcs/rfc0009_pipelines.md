# RFC0009 - Pipelines

## Summary

The OpenALPR integration is supported at present as a way of detecting and extracting licence info from an image.

This is one of several image processing options in Home Assistant, and a framework that can be extended further.

Allow a pipeline to be defined that links 1 or more of these image processors, using conditions to optionally control next steps ( or reuse a Home Assistant sequence type helper ). Any camera/zone or selected object type in a zone/camera can have one of these pipelines attached, so it executes on every image.
