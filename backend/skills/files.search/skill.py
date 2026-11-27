from jarvis.skills.files import search_files


def run(args, context):
    return {
        "results": search_files(
            args["query"],
            settings=context.settings,
            max_results=args.get("max_results"),
        ),
        "untrusted": True,
    }
