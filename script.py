import boto3
import logging
import json

region = 'us-east-1'

ec2 = boto3.resource('ec2', region_name=region)
cw = boto3.client('cloudwatch')
ec2client = boto3.client('ec2')

def get_ebs(instance_id):
    instance = ec2.Instance(instance_id)
    volumes = instance.volumes.all()
    ebs_list = [v.id for v in volumes]
    return ebs_list

def get_speed(instances):
    answer_from_ec2_client = ec2client.describe_instance_types(InstanceTypes=instances)
    network_per_instance = {
        "InstanceTypes": {}
    }
    for instance in answer_from_ec2_client['InstanceTypes']:
        instance_details = {
            instance['InstanceType']: {
                "EbsInfo" : instance['EbsInfo'],
                "NetworkInfo": instance['NetworkInfo']
            }
        }
        network_per_instance['InstanceTypes'].update(instance_details)
    return network_per_instance

def create_cw_dashboard(ec2_list, networklimit):
    widgets = {"widgets": []}

    # EBS to the EC2
    for ec2instance in ec2_list:
        ## New instance Header
        new_widget = {
            "type": "text",
            "width": 24,
            "height": 2,
            "properties": {
                "markdown": "\n# " + ec2instance +"\n"
            }
        }
        widgets['widgets'].append(new_widget)

        ## Instance -> Internet Gateway
        ec2instance_type = ec2.Instance(ec2instance)
        ec2_details = ec2client.describe_instance_types(InstanceTypes=[ec2instance_type.instance_type])
        new_widget = {
            "type": "text",
            "width": 24,
            "height": 2,
            "properties": {
                "markdown": "\n## " + "EC2 (" + ec2instance_type.instance_type + ") --> " + "Internet Gateway" +"\n"
            }
        }
        widgets['widgets'].append(new_widget)
        ec2_NetworkInfo = ec2_details['InstanceTypes'][0]['NetworkInfo']
        # Extract the number
        numbers = []
        for word in ec2_NetworkInfo['NetworkPerformance'].split():
            if word.isdigit():
                numbers.append(int(word))

        new_widget = {
            "type": "metric",
            "width": 24,
            "properties": {
                "metrics": [
                    [ { "expression": "m1/PERIOD(m1)+m1/PERIOD(m2)", "label": "Total Bandwidth", "id": "e1", "visible": False } ], #((read bytes * read ops) + (write bytes * write ops)) / period
                    [ { "expression": "e1*0.000008", "label": "Bandwidth (Mbps)", "id": "e2" } ], # Convert Bytes to Megabits -> 1 B = 0.000008 Mb
                    [ "AWS/EC2", "NetworkIn", "InstanceId", ec2instance, { "visible": False, "id": "m1" } ],
                    [ ".", "NetworkOut", ".", ".", { "visible": False, "id": "m2" } ]
                ],
                "view": "timeSeries",
                "stacked": False,
                "region": region,
                "stat": "Sum",
                "period": 300,
                "title": ec2instance + " -> IG",
                "annotations": {
                    "horizontal": [
                        {
                            "label": "Maximum Throughput (Mbps)",
                            "value": numbers[0]*1000
                        }
                    ]
                }
            }
        }
        widgets['widgets'].append(new_widget)


        ## Instance -> EBS
        new_widget = {
            "type": "text",
            "width": 24,
            "height": 2,
            "properties": {
                "markdown": "\n## " + "EC2" + " --> " + "EBS" +"\n"
            }
        }
        widgets['widgets'].append(new_widget)
        if(networklimit['InstanceTypes'][ec2instance_type.instance_type]['EbsInfo']['EbsOptimizedSupport'] != 'unsupported'):
            network_to_ebs = networklimit['InstanceTypes'][ec2instance_type.instance_type]['EbsInfo']['EbsOptimizedInfo']['MaximumBandwidthInMbps']
            network_to_ebs_half = network_to_ebs*0.5
        else:
            network_to_ebs = 0
            network_to_ebs_half = 0
        new_widget = {
            "type": "metric",
            "width": 24,
            "properties": {
                "metrics": [
                    [ { "expression": "m1/PERIOD(m1)+m1/PERIOD(m2)", "label": "Total IO In Bytes", "id": "e1", "visible": False } ], #((read bytes * read ops) + (write bytes * write ops)) / period
                    [ { "expression": "e1*0.000008", "label": "Bandwidth (Mbps)", "id": "e2" } ], # Convert Bytes to Megabits -> 1 B = 0.000008 Mb
                    [ "AWS/EC2", "EBSReadBytes", "InstanceId", ec2instance, { "visible": False, "id": "m1" } ],
                    [ ".", "EBSWriteBytes", ".", ".", { "visible": False, "id": "m2" } ],
                    [ ".", "EBSReadOps", ".", ".", { "visible": False, "id": "m3" } ],
                    [ ".", "EBSWriteOps", ".", ".", { "visible": False, "id": "m4" } ]
                ],
                "view": "timeSeries",
                "stacked": False,
                "region": region,
                "stat": "Sum",
                "period": 300,
                "title": ec2instance + " -> EBS",
                "annotations": {
                    "horizontal": [
                        {
                            "label": "Maximum Throughput (Mbps)",
                            "value": network_to_ebs
                        },
                        {
                            "label": "50% Throughput (Mbps)",
                            "value": network_to_ebs_half
                        }
                    ]
                }
            }
        }
        widgets['widgets'].append(new_widget)

        ## EBS -> Instance
        new_widget = {
            "type": "text",
            "width": 24,
            "height": 2,
            "properties": {
                "markdown": "\n## EBS --> EC2 \n"
            }
        }
        widgets['widgets'].append(new_widget)

        ebs_volumes = get_ebs(ec2instance) ## get all EBS volumes per instance

        for volume in ebs_volumes:
            volume_speed = ec2.Volume(volume)
            new_widget = {
                "type": "text",
                "width": 24,
                "height": 2,
                "properties": {
                    "markdown": "\n### InstanceID: " +ec2instance + " Volume: "+ volume +" ("+volume_speed.volume_type +")\n"
                }
            }
            widgets['widgets'].append(new_widget)
            ## Volume Throughput
            new_widget = {
                "type": "metric",
                "width": 12,
                "properties": {
                    "metrics": [
                        [ { "expression": "m1/PERIOD(m1)+m1/PERIOD(m2)", "label": "Total IO Bytes", "id": "e1", "visible": False, "stat": "Sum", "period": 300 } ],
                        [ { "expression": "e1*0.000001", "label": "Total Throughput (MiB/s)", "id": "e2", "stat": "Sum", "period": 300 } ], ## 1 B = 0.000001 MB
                        [ "AWS/EBS", "VolumeWriteBytes", "VolumeId", volume, { "visible": False, "id": "m1" } ],
                        [ ".", "VolumeReadBytes", ".", ".", { "visible": False, "id": "m2" } ],
                        [ ".", "VolumeWriteOps", ".", ".", { "visible": False, "id": "m3" } ],
                        [ ".", "VolumeReadOps", ".", ".", { "visible": False, "id": "m4" } ]
                    ],
                    "view": "timeSeries",
                    "stacked": False,
                    "region": region,
                    "stat": "Sum",
                    "period": 300,
                    "yAxis": {
                        "left": {
                            "showUnits": False,
                            "label": "MiB/s"
                        },
                        "right": {
                            "showUnits": False
                        }
                    },
                    "title": "Throughput" + "(" + volume +")"
                }
            }

            # Add space for annotations
            new_widget['properties'].update({'annotations': {'horizontal': []}})
            flagForIOPS = True

            if volume_speed.volume_type == "gp2":
                if (volume_speed.size < 170):
                    new_widget['properties']['annotations']['horizontal'].append({"label": "Maximum Throughput (MBps)","value": 128})
                if (volume_speed.size > 170 and volume_speed.size < 334):
                    new_widget['properties']['annotations']['horizontal'].append({"label": "Maximum Throughput (MBps) ** (if burst credits are available)","value": 250})
                if (volume_speed.size > 334):
                    new_widget['properties']['annotations']['horizontal'].append({"label": "Maximum Throughput (MBps)","value": 250})
            if volume_speed.volume_type == "io2" or volume_speed.volume_type == "io1":
                new_widget['properties']['annotations']['horizontal'].append({"label": "Maximum Throughput (MBps)","value": 1000})
            if volume_speed.volume_type == "st1":
                new_widget['properties']['annotations']['horizontal'].append({"label": "Maximum Throughput (MBps)","value": 500})
                flagForIOPS = False
            if volume_speed.volume_type == "sc1":
                new_widget['properties']['annotations']['horizontal'].append({"label": "Maximum Throughput (MBps)","value": 250})
                flagForIOPS = False
            if  volume_speed.volume_type == "gp3":
                new_widget['properties']['annotations']['horizontal'].append({"label": "Baseline Throughput (MBps)","value": volume_speed.throughput})

            widgets['widgets'].append(new_widget)
            iopsValue = 0

            if bool(flagForIOPS):
                iopsValue = volume_speed.iops
            else:
                iopsValue = 0

            # Volume IOPS
            new_widget = {
                "type": "metric",
                "width": 12,
                "properties": {
                    "metrics": [
                        [ { "expression": "m3/PERIOD(m3)+m4/PERIOD(m4)", "label": "Total IOPS", "id": "e1", "visible": False, "stat": "Sum", "period": 300 } ],
                        [ { "expression": "m3/PERIOD(m3)+m4/PERIOD(m4)", "label": "Total IOPS", "id": "e2", "stat": "Sum", "period": 300 } ],
                        [ "AWS/EBS", "VolumeWriteBytes", "VolumeId", volume, { "visible": False, "id": "m1" } ],
                        [ ".", "VolumeReadBytes", ".", ".", { "visible": False, "id": "m2" } ],
                        [ ".", "VolumeWriteOps", ".", ".", { "visible": False, "id": "m3" } ],
                        [ ".", "VolumeReadOps", ".", ".", { "visible": False, "id": "m4" } ]
                    ],
                    "view": "timeSeries",
                    "stacked": False,
                    "region": region,
                    "stat": "Sum",
                    "period": 300,
                    "yAxis": {
                        "left": {
                            "showUnits": False,
                            "label": "IOPS"
                        },
                        "right": {
                            "showUnits": False
                        }
                    },
                    "title": "IOPS" + "(" + volume +")",
                    "annotations": {
                    "horizontal": [
                        {
                            "label": "Baseline performance - IOPS",
                            "value": iopsValue
                        }
                    ]
                }
                }
            }
            if volume_speed.volume_type == "gp2":
                new_widget['properties']['annotations']['horizontal'].append({"label": "Burst IOPS","value": 3000})
            if volume_speed.volume_type == "gp3":
                new_widget['properties']['annotations']['horizontal'].append({"label": "Burst IOPS","value": 3000})
            widgets['widgets'].append(new_widget)

    dashboard = {"widgets": widgets['widgets']}
    result = cw.put_dashboard(DashboardName='EC2-EBS-Monitor',DashboardBody=json.dumps(dashboard))
    print(result)

def get_instance_type_from_ids(instances):
    list_of_instance_types = []

    for instance in instances:
        ec2instance = ec2.Instance(instance)
        instance_type = ec2instance.instance_type
        if(instance_type not in list_of_instance_types):
            list_of_instance_types.append(instance_type)

    return list_of_instance_types


InstanceList = ["i-08e34af30001259cd"]

Instance_Speed = get_speed(get_instance_type_from_ids(InstanceList))

create_cw_dashboard(InstanceList,Instance_Speed)