# What is it?

If you find AWS Cloudwatch logs a pain in the ass, and would like to download a log stream of a log group locally
and would rather tail on the log, this application will download the log file for you.   

# How do I run it?
Set up the configuration:

1. 
```
export AWS_ACCESS_KEY=xxxxxx
export AWS_SECRET_KEY=xxxxxx 
export MIXPANEL_TOKEN=xxxxxx
export LOG_GROUP_NAME=/ecs/<log group>  # log group to fetch
export CWL_ENV=<your env namespace>  # defaults to dev
export STREAM_LOOKBACK_COUNT=1  # the number of streams you need to process (default 1) ordered by latest streams  
```

```export MIXPANEL_TOKEN=xxxx``` if you want to report the log events to Mixpanel
```export AWS_LOGS_DIRECTORY=aws-logs``` if you want to write the log events to local file system



2. Run the [pex](https://pex.readthedocs.io/en/stable/) executable
```
./cloudwatchlogs.pex 
```

You should see the logs being downloaded under the `aws_logs` directory grouped by the log group directory and all the log streams desired under the directory as separate file(s)

# Logs
You can view the daemon logs at `cwl.log`


# Development

```
1. Install pip
2. pip install wheel
3. rm -rf ~/.pex/ && rm cloudwatchlogs.pex && rm cloudwatchlogs-1.0-py2-none-any.whl
4. pip wheel -w . . && pex -f $PWD cloudwatchlogs mixpanel boto3 python-slugify -m cloudwatch.main -o cloudwatchlogs.pex
```

## Maintaining State
A state file (checkpoint) is maintained under the project directory named `cwl.state`. This file contains the last time the file was modified and a map of log stream to the last processed `nextToken` so if the process dies, it can read from the state and resume from that point.

## Monitoring
1. Monitor if the files are being written to with system leven information like total file size(s) etc. [TODO]
2. Monitor the daemon processes are alive or not. [DONE]
