from jarvis.skills.web_search import brave_search


async def run(args, context):
    results = await brave_search(
        args["query"],
        count=args.get("count", context.settings.web_search_results),
        settings=context.settings,
    )
    return {"results": results, "untrusted": True}
